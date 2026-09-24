"""회귀 — 수집기 서버 설정화 v1.27.0 (대표 확정 2026-09-23 「서버 배포만으로」 · 시안 「추천대로 확정」)

지키는 것:
  ① 서버 기본값·안전선 = 수집기(remote_settings.js)의 기본값·안전선 — node 로 그 파일을 실행해 한 칸씩 대조.
  ② 서버가 자르는 규칙 = 수집기가 자르는 규칙(같은 입력 → 같은 출력). 그래야 「보낸 값 = 쓴 값」이다.
  ③ 이번 배포는 **동작 변화 0** — SETTINGS·기계별·배정·명령 전부 비어 있고, 기본값 = v1.26.0 박힌 값.
  ④ 값을 바꾸고 번호(SETTINGS_REV)를 안 올리면 막는다(REV_LEDGER).
  ⑤ 대표 확정 ④ — 캡차 쉼은 1시간 밑으로 못 줄이고, 쉼을 푸는 명령은 없다.
  ⑥ 기계 배정·한 번짜리 명령 거르기(만료·모르는 종류·다른 기계·시간대 붙은 만료).
  ⑦ 신호 표에 적용 보고 저장 · 화면 문구(적용됨/대기/미보고) · 서버 멈춤 상태 문구.
  ⑧ 로그·진단 보관(최근 5건 · 모르는 종류 거절 · 250KB).
  ⑨ 서버 배선 — /keywords·heartbeat 응답에 settings · /report 토큰·잠금 견딤 · /reports 관리자 전용 · 화면 칸.

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없다. 모듈은 가짜 DB 로, 배선은 소스(호출 모양)로.
"""
import json
import os
import re
import sqlite3
import subprocess
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


RS_PATH = os.path.join(ROOT, "collector-extension", "remote_settings.js")


def node(js):
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[:400])
    return json.loads(out.stdout)


import collector_settings as cs

print("① 기본값·안전선 — 수집기 파일과 한 칸씩 대조")
js = node(f"const R=require({json.dumps(RS_PATH)}); process.stdout.write(JSON.stringify({{d:R.DEFAULTS,f:R.FENCES,i:R.INTEGER_KEYS,p:R.PAIRS,c:R.COMMAND_KINDS}}))")
ok("기본값 칸 이름이 같다", set(js["d"]) == set(cs.DEFAULTS), str(set(js["d"]) ^ set(cs.DEFAULTS)))
diff = [k for k in cs.DEFAULTS if js["d"].get(k) != cs.DEFAULTS[k]]
ok("기본값이 한 칸도 다르지 않다", not diff, str(diff))
ok("안전선 칸 이름이 같다", set(js["f"]) == set(cs.FENCES))
fdiff = [k for k in cs.FENCES if list(js["f"].get(k, [])) != list(cs.FENCES[k])]
ok("안전선 값이 한 칸도 다르지 않다", not fdiff, str(fdiff))
ok("정수 칸 목록이 같다", set(js["i"]) == set(cs.INTEGER_KEYS))
ok("최소·최대 짝이 같다", [tuple(x) for x in js["p"]] == [tuple(x) for x in cs.PAIRS])
ok("명령 종류가 같다", tuple(js["c"]) == tuple(cs.COMMAND_KINDS))
ok("모든 안전선 칸에 기본값이 있고 기본값이 선 안에 있다",
   all(k in cs.DEFAULTS and cs.FENCES[k][0] <= cs.DEFAULTS[k] <= cs.FENCES[k][1] for k in cs.FENCES))

print("\n② 자르는 규칙 — 서버 = 수집기(같은 입력 → 같은 출력)")
CASES = [
    {},
    {"spreadMinMs": 1000, "pagesPerKeyword": 99, "blockCooldownMs": 60000},
    {"spreadMinMs": "40000", "readTries": None, "machinePaused": "yes", "swSearchEntry": 1},
    {"pageGapMinMs": 5000, "pageGapMaxMs": 2000, "spreadLo": 2, "spreadHi": 0.5},
    {"onDemandHourCap": 2.5, "logKeep": 50.5, "readTriesPaged": 7.49},
    {"extraBlockPhrases": ["  새 차단 문구 ", "a", "x" * 61, 3, "새 차단 문구", "둘째"]},
    {"swCoordinated": None, "swSearchEntry": False, "swEarlyStop": False, "machinePaused": True},
    {"unknownKey": 1, "slowFactor": 9, "heartbeatMin": 0, "slowWindowMs": -5},
    {"onDemandHourCap": True, "hourBudgetMs": 99999999},
]
js_out = node(f"const R=require({json.dumps(RS_PATH)}); const C={json.dumps(CASES)};"
              "process.stdout.write(JSON.stringify(C.map(c=>R.merge(c).values)))")
mism = [i for i, c in enumerate(CASES) if cs._clamp_values(c) != js_out[i]]
ok(f"{len(CASES)}가지 입력에서 서버·수집기 결과가 같다", not mism,
   "; ".join(f"#{i}: py={cs._clamp_values(CASES[i])} js={js_out[i]}" for i in mism[:2]))
v = cs._clamp_values({"spreadMinMs": 1000, "blockCooldownMs": 60000, "pagesPerKeyword": 99})
ok("안전선 밖 → 가장 가까운 선(간격 20초 · 쉼 1시간 · 깊이 10장)",
   v["spreadMinMs"] == 20000 and v["blockCooldownMs"] == 3600000 and v["pagesPerKeyword"] == 10)
v = cs._clamp_values({"pageGapMinMs": 5000, "pageGapMaxMs": 2000})
ok("최소가 최대보다 크면 최대를 최소에 맞춘다", v["pageGapMinMs"] == 5000 and v["pageGapMaxMs"] == 5000)
ok("정수 칸 반올림이 수집기(Math.round)와 같다 — 2.5 → 3", cs._clamp_values({"onDemandHourCap": 2.5})["onDemandHourCap"] == 3)
ok("참/거짓을 숫자 칸에 넣으면 버린다(파이썬 bool 은 int 라 따로 막아야 한다)",
   cs._clamp_values({"onDemandHourCap": True})["onDemandHourCap"] == 12)

print("\n③ 지금 설정 — 공통 값은 기본값 그대로 · 서버 자동 배정은 두 대 다 끔(2026-09-24 되돌림 · 수집기 v1.27.1 대기)")
ok("SETTINGS 비어 있음(두 대 공통 값 = 기본값)", cs.SETTINGS == {})
ok("기계 배정 비어 있음(= 팝업 값 그대로)", cs.ASSIGNMENTS == {})
ok("명령 비어 있음", cs.COMMANDS == [])
_v1, _v2 = cs.values_for(1), cs.values_for(2)
ok("🔴 1번은 자동 배정 끔(팝업이 켜져 있어도 서버 값이 우선)", _v1["swCoordinated"] is False)
ok("🔴 2번도 자동 배정 끔(되돌림 — 팝업이 켜져 있어도 서버 값이 우선)", _v2["swCoordinated"] is False)
ok("그 밖의 칸은 두 대 모두 기본값",
   {k: v for k, v in _v1.items() if k != "swCoordinated"} == {k: v for k, v in cs.DEFAULTS.items() if k != "swCoordinated"}
   and {k: v for k, v in _v2.items() if k != "swCoordinated"} == {k: v for k, v in cs.DEFAULTS.items() if k != "swCoordinated"})
ok("기계별 덮어쓰기는 자동 배정 칸만", all(set(o) == {"swCoordinated"} for o in cs.WORKER_OVERRIDES.values()))

print("\n③-2 서버 자동 배정 스위치(collector_coord 정책 위에 얹기)")
import collector_coord as cc
_env_off = cc.policy_from_env({})
_p = cs.coord_policy(_env_off)
ok("🔴 .env 가 꺼져 있어도 이 파일이 켠다", _env_off.enabled is False and _p.enabled is True)
ok("🔴 기계당 시간 15 = 지금 시험 상한과 같다 · 하루 360", _p.worker_hourly == 15 and _p.worker_daily == 360)
ok("나머지 정책은 .env 기본값 그대로(전체 40 · 간격 40 · 깊이 300)",
   _p.global_hourly == 40 and _p.min_gap_seconds == 40 and _p.requested_depth == 300)
try:
    import collect_cap as _cap
    ok("기계당 시간 상한이 서버 시험 상한(collect_cap)과 같다", _p.worker_hourly == _cap.DEFAULT_TEST_CAP)
except Exception as _e:
    ok("기계당 시간 상한이 서버 시험 상한(collect_cap)과 같다 — 못 쟀다", False, str(_e))
_saveE, _saveP = cs.COORD_ENABLED, dict(cs.COORD_POLICY)
cs.COORD_POLICY.clear(); cs.COORD_POLICY.update({"worker_hourly": -1})
ok("🔴 정책 값이 틀리면 꺼짐(안전)", cs.coord_policy(_env_off).enabled is False)
cs.COORD_POLICY.clear(); cs.COORD_POLICY.update({"no_such_field": 5})
ok("모르는 칸은 버린다", cs.coord_policy(_env_off).enabled is True)
cs.COORD_ENABLED = None; cs.COORD_POLICY.clear()
_env_on = cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1"})
ok("비어 있으면 .env 그대로(종전 동작)", cs.coord_policy(_env_off) is _env_off and cs.coord_policy(_env_on) is _env_on)
_fp_none = cs.config_fingerprint()
cs.COORD_ENABLED = False
ok("🔴 끄기만 해도 지문이 달라진다(REV 를 안 올리면 게이트가 막는다)", cs.config_fingerprint() != _fp_none)
ok("이 파일이 끄면 .env 가 켜져 있어도 꺼짐", cs.coord_policy(_env_on).enabled is False)
cs.COORD_ENABLED = _saveE; cs.COORD_POLICY.clear(); cs.COORD_POLICY.update(_saveP)
v2src = read("backend/collector_v2.py")
pol = v2src[v2src.index("def policy()"):v2src.index("def requested()")]
ok("🔴 collector_v2.policy() 가 설정 파일 스위치를 얹는다 · 고장 나면 .env 그대로",
   "core.policy_from_env()" in pol and "_cs.coord_policy(base)" in pol and "except Exception" in pol and "return base" in pol)
bg = read("collector-extension/background.js")
cfg = bg[bg.index("const CFG = {"):bg.index("const _rawSleep")]


def cfg_num(key):
    m = re.search(rf"\b{key}:\s*([0-9 *]+),", cfg)
    return eval(m.group(1)) if m else None   # noqa: S307 — 저장소 안 상수식(숫자·곱셈)만


pairs = {"pagesPerKeyword": "pagesPerKeyword", "readTries": "readTries", "readTriesPaged": "readTriesPaged",
         "readGapMs": "readGapMs", "minGapMs": "pageGapMinMs", "maxGapMs": "pageGapMaxMs",
         "onDemandGapMs": "onDemandGapMs", "onDemandHourCap": "onDemandHourCap",
         "hourBudgetMs": "hourBudgetMs", "maxConsecutiveFail": "maxConsecutiveFail"}
bad = [k for k, d in pairs.items() if cfg_num(k) != cs.DEFAULTS[d]]
ok("수집기 CFG 에 박힌 값 = 기본값(10칸)", not bad, str(bad))


def const_num(name):
    m = re.search(rf"const {name} = ([0-9 *]+);", bg)
    return eval(m.group(1)) if m else None   # noqa: S307


consts = {"LOG_KEEP": "logKeep", "SPREAD_MIN_MS": "spreadMinMs", "BLOCK_COOLDOWN_MS": "blockCooldownMs",
          "SLOW_WINDOW_MS": "slowWindowMs", "OUTBOX_MAX_ITEMS": "outboxMaxItems", "OUTBOX_MAX_ATTEMPTS": "outboxMaxAttempts",
          "DAILY_DUE_MS": "dailyDueMs", "HEARTBEAT_PERIOD_MIN": "heartbeatMin"}
bad = [k for k, d in consts.items() if const_num(k) != cs.DEFAULTS[d]]
ok("수집기 상수(폴백) = 기본값(8개)", not bad, str(bad))
ok("8장 → 300위(applyRuntime 의 maxRank 식이 기본값에서 300)", round(cs.DEFAULTS["pagesPerKeyword"] * 37.5) == 300
   and "CFG.maxRank = Math.round(v.pagesPerKeyword * 37.5);" in bg)

print("\n④ 값을 바꾸고 번호를 안 올리면 막는다")
ok("지금 번호가 장부에 있다", cs.SETTINGS_REV in cs.REV_LEDGER)
ok("🔴 장부의 지문 = 지금 SETTINGS·기계별 덮어쓰기의 지문",
   cs.REV_LEDGER.get(cs.SETTINGS_REV) == cs.config_fingerprint(),
   f"SETTINGS 를 고쳤으면 SETTINGS_REV 를 올리고 REV_LEDGER 에 {cs.config_fingerprint()} 를 더하세요")
_save = dict(cs.SETTINGS)
cs.SETTINGS["pageGapMinMs"] = 2000
ok("(자체 점검) 값만 바꾸면 지문이 달라진다", cs.config_fingerprint() != cs.REV_LEDGER[cs.SETTINGS_REV])
cs.SETTINGS.clear(); cs.SETTINGS.update(_save)

print("\n⑤ 대표 확정 ④ — 캡차 쉼")
ok("🔴 캡차 쉼 안전선 하한 1시간", cs.FENCES["blockCooldownMs"][0] >= 3600000)
ok("🔴 쉼을 푸는 명령이 없다", not any(re.search(r"block|unblock|rest|clear", k, re.I) for k in cs.COMMAND_KINDS))
rs = read("collector-extension/remote_settings.js")
ok("🔴 수집기 쪽 명령 목록에도 없다", "clearBlocked" not in rs and "unblock" not in rs.lower())
run_now = bg[bg.index("else if (c.kind === 'runNow')"):bg.index("else if (c.kind === 'runNow')") + 400]
ok("🔴 runNow 는 수동 실행(쉼 해제)이 아니라 runCollection(false)", "runCollection(false)" in run_now and "runCollection(true)" not in run_now)

print("\n⑥ 배정·명령 거르기")
cs.ASSIGNMENTS.update({"i-ok": {"no": 2, "count": 2}, "i-bad": {"no": 3, "count": 2}, "i-junk": {"no": "x"}})
ok("정상 배정", cs.assignment_for("i-ok") == {"no": 2, "count": 2})
ok("번호가 대수보다 크면 무시", cs.assignment_for("i-bad") is None)
ok("형식이 틀리면 무시", cs.assignment_for("i-junk") is None and cs.assignment_for("") is None)
_saveW = {k: dict(v) for k, v in cs.WORKER_OVERRIDES.items()}
cs.WORKER_OVERRIDES.clear()
cs.WORKER_OVERRIDES[2] = {"pageGapMinMs": 2500, "pageGapMaxMs": 5000}
st = cs.settings_for(1, "i-ok")
ok("🔴 서버가 2번으로 정한 기계에는 2번 덮어쓰기가 간다(팝업이 1번이라 해도)",
   st["assign"] == {"no": 2, "count": 2} and st["values"]["pageGapMinMs"] == 2500)
ok("다른 기계(1번)는 기본값", cs.settings_for(1)["values"]["pageGapMinMs"] == 1200)
ok("기계마다 지문이 다르다", cs.settings_for(1)["hash"] != st["hash"])
cs.WORKER_OVERRIDES.clear(); cs.WORKER_OVERRIDES.update(_saveW); cs.ASSIGNMENTS.clear()
now = datetime(2026, 9, 24, 10, 0, 0)
cs.COMMANDS.extend([
    {"id": "c1", "kind": "uploadLogs", "until": "2026-09-24T12:00:00", "worker": None},
    {"id": "c2", "kind": "uploadLogs", "until": "2026-09-24T09:00:00", "worker": None},     # 만료
    {"id": "c3", "kind": "clearBlocked", "until": "2026-09-24T12:00:00", "worker": None},   # 모르는 종류
    {"id": "c4", "kind": "runNow", "until": "2026-09-24T12:00:00", "worker": 2},            # 다른 기계
    {"id": "c5", "kind": "rearmAlarms", "until": "2026-09-24T12:00:00+09:00", "worker": 1},  # 시간대 붙은 만료
    {"id": "c6", "kind": "flushOutbox", "until": "엉터리", "worker": None},                 # 형식 틀림
])
got = [c["id"] for c in (cs.settings_for(1, None, now=now).get("commands") or [])]
ok("만료·모르는 종류·다른 기계·형식 틀림은 안 보낸다", "c1" in got and not ({"c2", "c3", "c4", "c6"} & set(got)), str(got))
cs.COMMANDS.clear()
ok("명령이 없으면 commands 칸 자체가 없다", "commands" not in cs.settings_for(1))

print("\n⑦ 신호 표 — 적용 보고 · 화면 문구")
import collector_heartbeat as hb
conn = sqlite3.connect(":memory:")
t0 = datetime(2026, 9, 24, 10, 0, 0)
hb.record(conn, {"instanceId": "old", "workerNo": 1, "workerCount": 2, "extVersion": "1.26.0"}, now=t0)
exp = cs.expected_hash(2)
hb.record(conn, {"instanceId": "new", "workerNo": 2, "workerCount": 2, "extVersion": "1.27.0",
                 "settingsRev": 1, "settingsHash": exp, "settingsNote": "", "commandsDone": ["c1"],
                 "pausedByServer": False}, now=t0)
hb.record(conn, {"instanceId": "stale", "workerNo": 1, "workerCount": 2, "extVersion": "1.27.0",
                 "settingsRev": 0, "settingsHash": "deadbeef", "pausedByServer": True}, now=t0)
ms = {m["instance_id"]: m for m in hb.machines(conn, now=t0 + timedelta(minutes=1))}
ok("옛 수집기 = 「설정 미보고」 · 판정 없음", ms["old"]["settingsText"].startswith("설정 미보고") and ms["old"]["settingsMatch"] is False)
ok("🔴 새 수집기가 지금 지문을 쓰면 「적용됨」 · 초록", ms["new"]["settingsText"] == "⚙ 1번 적용됨" and ms["new"]["settingsMatch"] is True)
ok("지문이 다르면 「대기」", "대기" in ms["stale"]["settingsText"] and ms["stale"]["settingsMatch"] is False)
ok("실행한 명령 id 가 남는다", ms["new"]["commands_done"] == "c1")
ok("🔴 서버가 멈춘 기계는 상태가 「서버가 이 기계를 멈춤」", "서버가 이 기계를 멈춤" in ms["stale"]["status"])
ok("사람이 누른 일시정지가 서버 멈춤보다 먼저 보인다", hb.status_text({"last_seen": t0.strftime("%Y-%m-%d %H:%M:%S"), "paused_local": 1, "paused_server": 1}, t0).startswith("⏸ 일시정지"))

print("\n⑧ 로그·진단 보관")
import collector_reports as cr
c2 = sqlite3.connect(":memory:")
for i in range(8):
    cr.save(c2, "m1", "logs", f"줄 {i}", now=t0 + timedelta(minutes=i))
ok("기계·종류별 최근 5건만", len(cr.latest(c2, "m1", "logs", 50)) == 5 and cr.latest(c2, "m1", "logs", 1)[0]["body"] == "줄 7")
ok("모르는 종류는 거절", cr.save(c2, "m1", "secrets", "x")["saved"] is False)
ok("instanceId 없으면 거절", cr.save(c2, "", "logs", "x")["saved"] is False)
big = cr.save(c2, "m1", "diag", "가" * 200000)
ok("250KB 로 자른다(한글이 반쯤 잘려도 깨지지 않는다)", big["saved"] and big["bytes"] <= cr.MAX_BYTES)

print("\n⑨ 서버 배선(소스)")
src = read("backend/collector.py")
kw = src[src.index('@router.get("/keywords")'):src.index("def _get_collect_keywords(")]
ok("🔴 /keywords 응답은 전부 _with_settings 를 지난다(중지·전량·시간대 세 갈래 모두)",
   "resp = _get_collect_keywords(hour, worker, workers, x_collector_token)" in kw and "return _with_settings(resp, worker_no)" in kw)
ok("/keywords 토큰 검사는 그대로(안쪽 함수에서)", "_auth(x_collector_token)" in src[src.index("def _get_collect_keywords("):src.index("def _get_collect_keywords(") + 1500])
hbsrc = src[src.index('@router.post("/heartbeat")'):src.index('@router.post("/blocked")')]
ok("🔴 heartbeat 응답에 settings(기계 번호·instanceId 로)", '_with_settings({"success": True, "serverTime": row["last_seen"]}, row.get("worker_no"), row.get("instance_id"))' in hbsrc)
ws = src[src.index("def _with_settings("):src.index('@router.get("/keywords")')]
ok("설정 싣기가 실패해도 응답은 나간다(try/except)", "except Exception" in ws)
rep = src[src.index('@router.post("/report")'):src.index('@router.get("/reports")')]
ok("/report 는 토큰 검사 · 잠금 견딤(write_with_retry) · 503", "_auth(x_collector_token)" in rep and "write_with_retry(DB_PATH" in rep and "status_code=503" in rep)
reps = src[src.index('@router.get("/reports")'):src.index('@router.get("/control")')]
ok("/reports 는 관리자 전용", 'current_user.get("role") not in ("admin", "superadmin")' in reps and "403" in reps)
ok("/report 로그 본문을 서버 로그에 찍지 않는다(크기만)", "req.text" not in rep.split("logger.info")[1][:200])
for f in ("settingsRev", "settingsHash", "settingsNote", "commandsDone", "pausedByServer"):
    ok(f"HeartbeatReport 에 {f}", re.search(rf"\b{f}: Optional", src) is not None)
jsx = read("frontend/js/components/KeywordRankPage.jsx")
ok("화면 「수집기 운영」 표에 ⚙ 서버 설정 칸", "'⚙ 서버 설정'" in jsx and "m.settingsText" in jsx)

print(f"\n{passed} passed · {failed} failed")
sys.exit(1 if failed else 0)
