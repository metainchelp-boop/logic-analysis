"""회귀 — 수집 중앙 배정(코디네이터 · 코덱스 1.22.0 이식판) · 2026-09-22 2차

지키는 것:
  ① sync_daily — 유니버스 전부에 작업(목표 없어도 = B1) · 깊이 임의값(B2) · 오늘 수집분 있으면 done · 멱등.
  ② register/claim — 임대 1건 · 같은 기계 재요청은 같은 임대 · 다른 기계는 다른 키워드 · 기계 분할 존중 · 슬롯 순서.
  ③ 예산 — 기계 시간 상한 넘으면 WAIT_BUDGET(+nextAllowedAt) · 간격(pace) · 전역 상한.
  ④ 임대 만료 회수 · release 재시도/held · complete done/deferred/held + pace 갱신.
  ⑤ 막힘은 **그 기계만** 6시간(전역 정지 없음) · 쉼이 지나면 자동 READY · 화면 스위치/관리자 정지는 전역.
  ⑥ policy_from_env — 깨진 JSON 이면 꺼짐 · status/readiness 모양 · purge_old.
⚠️ stdlib 만.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); sys.path.insert(0, BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


import collector_coord as cc

P = cc.Policy(enabled=True, global_hourly=40, global_daily=1200, worker_hourly=3, worker_daily=240, min_gap_seconds=40,
              lease_seconds=600, session_seconds=900, requested_depth=300, transient_retries=1, retry_backoff_seconds=60)
NOW = int(datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).timestamp())
DAY = cc.business_day(NOW)
split_ok = lambda kw, w, wc: (sum(ord(c) for c in kw) % wc) == w
slot_of = lambda kw, prio: (sum(ord(c) for c in kw) % 24)

print("① sync_daily")
conn = sqlite3.connect(":memory:"); cc.init_db(conn)
uni = {"가": True, "각": True, "나": False, "낙": False, "마": True}   # 가·나·마 = 짝수합 · 각·낙 = 홀수합(분할 시험용)
r = cc.sync_daily(conn, DAY, uni, {"가": ["111"], "나": ["222", "333"]}, slot_of, depth=120, done_keywords=["마"])
jobs = {j["keyword"]: j for j in cc._rows(conn, "SELECT * FROM collector_coord_jobs")}
ok("🔴 유니버스 5개 전부 작업 생성(목표 없는 각·낙 포함 = B1)", r["made"] == 5 and set(jobs) == set(uni))
ok("🔴 깊이 120 도 그대로(B2)", all(j["requested_depth"] == 120 for j in jobs.values()))
ok("목표가 실린다 · 오늘 수집분 있는 마 는 done", json.loads(jobs["가"]["targets_json"]) == ["111"] and json.loads(jobs["각"]["targets_json"]) == [] and jobs["마"]["state"] == "done")
r2 = cc.sync_daily(conn, DAY, uni, {"가": ["111", "999"], "나": ["222", "333"]}, slot_of, depth=120, done_keywords=["마"])
ok("멱등 — 다시 돌리면 새로 안 만들고 목표만 갱신", r2["made"] == 0 and r2["updated"] == 1 and cc._one(conn, "SELECT COUNT(*) n FROM collector_coord_jobs")["n"] == 5)

print("\n② register / claim")
w1 = cc.register(conn, "W1", "S1", "1.24.0", 1, 2, NOW, P)
w2 = cc.register(conn, "W2", "S2", "1.24.0", 2, 2, NOW, P)
ok("등록 응답에 정책·상태가 실린다", w1["state"] == "READY" and w1["enabled"] is True and w1["policy"]["worker_hourly"] == 3)
c1 = cc.claim(conn, "W1", "S1", NOW, P, hour=10, split_ok=split_ok)
ok("🔴 임대 1건(LEASED · job 계약 실림)", c1["state"] == "LEASED" and c1["job"]["leaseId"] and c1["job"]["workerId"] == "W1")
ok("🔴 기계 분할 존중 — W1(0번) 몫만", split_ok(c1["job"]["keyword"], 0, 2))
c1b = cc.claim(conn, "W1", "S1", NOW + 5, P, hour=10, split_ok=split_ok)
ok("같은 기계가 다시 부르면 같은 임대를 돌려준다(중복 배정 없음)", c1b["state"] == "LEASED" and c1b["job"]["leaseId"] == c1["job"]["leaseId"])
c2 = cc.claim(conn, "W2", "S2", NOW, P, hour=10, split_ok=split_ok)
ok("🔴 다른 기계는 다른 키워드(1번 몫)", c2["state"] == "LEASED" and c2["job"]["keyword"] != c1["job"]["keyword"] and split_ok(c2["job"]["keyword"], 1, 2))
ok("세션이 다르면 SESSION_MISMATCH", cc.claim(conn, "W1", "다른세션", NOW, P, 10, split_ok)["state"] == "SESSION_MISMATCH")
ok("정책 꺼짐이면 INACTIVE(구경로로 폴백할 신호)", cc.claim(conn, "W1", "S1", NOW, cc.Policy(enabled=False), 10, split_ok)["state"] == "INACTIVE")

print("\n③ 예산·간격")
conn3 = sqlite3.connect(":memory:"); cc.init_db(conn3)
cc.sync_daily(conn3, DAY, {f"k{i}": True for i in range(10)}, {}, lambda k, p: 10, depth=300)
cc.register(conn3, "A", "sa", "1.24.0", 1, 1, NOW, P)
t = NOW; got = []
for i in range(5):
    r = cc.claim(conn3, "A", "sa", t, P, 10, split_ok)
    if r["state"] == "LEASED":
        got.append(r["job"]["keyword"]); cc.complete(conn3, r["job"], "complete", f"o{i}", t + 30); t += 60
    else:
        got.append(r["state"]); break
ok("🔴 기계 시간 상한 3 → 4번째는 WAIT_BUDGET + nextAllowedAt", got[:3] != [] and len([g for g in got if g.startswith("k")]) == 3 and got[3] == "WAIT_BUDGET")
r = cc.claim(conn3, "A", "sa", t, P, 10, split_ok)
ok("nextAllowedAt 는 첫 배정 + 3600", r.get("nextAllowedAt") == NOW + 3600)
r = cc.claim(conn3, "A", "sa", NOW + 3601, P, 10, split_ok)
ok("한 시간 지나면 다시 배정된다", r["state"] == "LEASED")
conn4 = sqlite3.connect(":memory:"); cc.init_db(conn4)
cc.sync_daily(conn4, DAY, {"x": True, "y": True}, {}, lambda k, p: 10)
cc.register(conn4, "B", "sb", "1.24.0", 1, 1, NOW, P)
a = cc.claim(conn4, "B", "sb", NOW, P, 10, split_ok); cc.complete(conn4, a["job"], "complete", "o", NOW + 20)
b = cc.claim(conn4, "B", "sb", NOW + 21, P, 10, split_ok)
ok("🔴 최소 간격 40초 안에는 다음 배정을 안 준다(WAIT_BUDGET)", b["state"] == "WAIT_BUDGET" and b["nextAllowedAt"] == NOW + 40)
ok("40초 뒤엔 준다", cc.claim(conn4, "B", "sb", NOW + 41, P, 10, split_ok)["state"] == "LEASED")

print("\n④ 임대 만료 · release · complete")
conn5 = sqlite3.connect(":memory:"); cc.init_db(conn5)
cc.sync_daily(conn5, DAY, {"p": True, "q": True, "r": True}, {}, lambda k, p: 10)
cc.register(conn5, "C", "sc", "1.24.0", 1, 1, NOW, P); cc.register(conn5, "D", "sd", "1.24.0", 1, 1, NOW, P)
lc = cc.claim(conn5, "C", "sc", NOW, P, 10, split_ok)
ld = cc.claim(conn5, "D", "sd", NOW + 601, P, 10, split_ok)   # C 의 임대가 만료된 뒤
ok("🔴 임대 만료(600초)면 다른 기계가 그 키워드를 이어받을 수 있다", ld["state"] == "LEASED" and
   cc._one(conn5, "SELECT state, reason FROM collector_coord_jobs WHERE job_id=?", (lc["job"]["jobId"],))["state"] in ("pending", "leased"))
ok("만료된 계약으로 complete 하면 LEASE_MISMATCH(버리지 않고 사유만)", cc.complete(conn5, lc["job"], "complete", "o", NOW + 602)["reason"] in ("LEASE_MISMATCH", "NOT_LEASED"))
rel = cc.release(conn5, ld["job"], NOW + 602, P, reason="WAIT_BUDGET")
ok("release 1회차 → pending + 백오프 60초", rel["state"] == "WAIT_BUDGET" and rel["nextAllowedAt"] == NOW + 602 + 60)
ld2 = cc.claim(conn5, "D", "sd", NOW + 700, P, 10, split_ok)
part = cc.complete(conn5, ld2["job"], "partial", "o2", NOW + 730, stop_reason="STALE_PAGE")
ok("🔴 partial → deferred(오늘 다시 · 10분 뒤) · 사유", part["state"] == "deferred" and part["reason"] == "STALE_PAGE")
ld3 = cc.claim(conn5, "D", "sd", NOW + 800, P, 10, split_ok)   # partial 벌점으로 간격 80초 — 그 뒤
fail_ = cc.complete(conn5, ld3["job"], "failed", "o3", NOW + 790, stop_reason="READ_FAILED")
ok("failed → held", fail_["state"] == "held")
pace = json.loads(cc._one(conn5, "SELECT pace_json FROM collector_coord_workers WHERE worker_id='D'")["pace_json"])
ok("실패는 pace 벌점(partial+failed 두 번 → penalty 4 · 간격 ↑ · 상한 4배)", pace.get("penalty") == 4.0 and 80 <= pace["intervalSeconds"] <= 160)

print("\n⑤ 막힘은 그 기계만")
conn6 = sqlite3.connect(":memory:"); cc.init_db(conn6)
cc.sync_daily(conn6, DAY, {"m": True, "n": True}, {}, lambda k, p: 10)
cc.register(conn6, "E", "se", "1.24.0", 1, 2, NOW, P); cc.register(conn6, "F", "sf", "1.24.0", 2, 2, NOW, P)
le = cc.claim(conn6, "E", "se", NOW, P, 10, lambda k, w, wc: True)
rp = cc.report(conn6, "E", "se", "PAUSED_BLOCK", NOW + 10, P, reason="캡차")
ok("🔴 막힘 보고 → 그 기계 paused_until = +6h · 쥐고 있던 임대 회수", rp["pausedUntil"] == NOW + 10 + 6 * 3600 and
   cc._one(conn6, "SELECT state FROM collector_coord_jobs WHERE job_id=?", (le["job"]["jobId"],))["state"] == "pending")
ok("🔴 그 기계 claim = PAUSED_BLOCK · **다른 기계는 그대로 배정**(전역 정지 없음)",
   cc.claim(conn6, "E", "se", NOW + 20, P, 10, lambda k, w, wc: True)["state"] == "PAUSED_BLOCK" and
   cc.claim(conn6, "F", "sf", NOW + 20, P, 10, lambda k, w, wc: True)["state"] == "LEASED")
ok("READY 보고해도 쉼이 안 지났으면 안 풀린다", cc.report(conn6, "E", "se", "READY", NOW + 100, P)["state"] == "PAUSED_BLOCK")
ok("🔴 6시간 지나면 사람 손 없이 자동 READY", cc.claim(conn6, "E", "se", NOW + 10 + 6 * 3600 + 1, P, 10, lambda k, w, wc: True)["state"] in ("LEASED", "IDLE", "WAIT_BUDGET")
   and cc._one(conn6, "SELECT state FROM collector_coord_workers WHERE worker_id='E'")["state"] == "READY")
cc.set_control(conn6, "PAUSED_OPERATOR", NOW + 200, "관리자")
ok("관리자 정지는 전역 — 모든 기계 PAUSED_OPERATOR · 임대 회수", cc.claim(conn6, "F", "sf", NOW + 201, P, 10, lambda k, w, wc: True)["state"] == "PAUSED_OPERATOR"
   and cc._one(conn6, "SELECT COUNT(*) n FROM collector_coord_jobs WHERE state='leased'")["n"] == 0)
cc.set_control(conn6, "READY", NOW + 300)
ok("화면 스위치(legacy_paused) 도 전역 정지로 본다", cc.claim(conn6, "F", "sf", NOW + 301, P, 10, lambda k, w, wc: True, legacy_paused=True)["state"] == "PAUSED_OPERATOR")
ok("새 세션으로 재등록하면 옛 세션 임대는 회수", (lambda: (cc.claim(conn6, "F", "sf", NOW + 302, P, 10, lambda k, w, wc: True), cc.register(conn6, "F", "sf2", "1.24.0", 2, 2, NOW + 303, P),
   cc._one(conn6, "SELECT COUNT(*) n FROM collector_coord_jobs WHERE state='leased' AND worker_id='F'")["n"] == 0)[-1])())

print("\n⑥ 정책·상태")
ok("🔴 env 꺼짐 = enabled False · 기본값은 서버 상한과 같다(40 · 기계 10 · 간격 40)", (lambda p: p.enabled is False and p.global_hourly == 40 and p.worker_hourly == 10 and p.min_gap_seconds == 40)(cc.policy_from_env({})))
ok("env 켬 + 정책 JSON 반영", cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1", "COLLECTOR_V2_POLICY_JSON": '{"worker_hourly": 12, "requested_depth": 80}'}).worker_hourly == 12
   and cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1", "COLLECTOR_V2_POLICY_JSON": '{"requested_depth": 80}'}).requested_depth == 80)
ok("🔴 정책 JSON 이 깨지면 켜져 있어도 **꺼진 것**으로(안전)", cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1", "COLLECTOR_V2_POLICY_JSON": "{bad"}).enabled is False)
ok("정책 값이 틀리면(음수) 꺼짐", cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1", "COLLECTOR_V2_POLICY_JSON": '{"worker_hourly": -1}'}).enabled is False)
st = cc.status(conn6, NOW + 400, P)
ok("status — jobs/claims/workers/policy", st["jobs"]["total"] == 2 and "lastHour" in st["claims"] and len(st["workers"]) == 2 and st["policy"]["enabled"] is True)
rd = cc.readiness(conn6, NOW + 400, P, env={"COLLECTOR_V2_ENABLED": "1"})
ok("readiness — blockers 목록 + 용량 + 기계", isinstance(rd["blockers"], list) and "capacity" in rd and rd["workers"]["total"] == 2)
rd2 = cc.readiness(sqlite3.connect(":memory:"), NOW, cc.Policy(enabled=False), env={"COLLECTOR_V2_ENABLED": "0"}) if False else None
c7 = sqlite3.connect(":memory:"); cc.init_db(c7)
rd2 = cc.readiness(c7, NOW, cc.Policy(enabled=False), env={"COLLECTOR_V2_ENABLED": "0"})
ok("꺼진 서버의 readiness 는 V2_DISABLED · 기계 없음 을 막힘으로 든다", "V2_DISABLED" in rd2["blockers"] and "NO_READY_ONLINE_WORKER" in rd2["blockers"] and rd2["configurationReady"] is False)
conn6.execute("INSERT INTO collector_coord_jobs(job_id, day, keyword) VALUES('old','2026-01-01','옛')"); conn6.commit()
ok("purge_old 는 14일 지난 작업만 지운다", cc.purge_old(conn6) == 1 and cc._one(conn6, "SELECT COUNT(*) n FROM collector_coord_jobs")["n"] == 2)

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
