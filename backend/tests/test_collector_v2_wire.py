"""회귀 — 수집 중앙 배정 v2 배선(코덱스 1.22.0 이식 2차 · 2026-09-22)

지키는 것(전부 소스 배선 — 배포 게이트에 fastapi 가 없어 collector_v2·collector·main 은 import 불가):
  ① collector_v2 — 확장 경로 4개(register·claim·report·release)는 토큰 검사(_token) · status/readiness 는 로그인 ·
     readiness/control 은 관리자 · claim 은 정책이 꺼져 있으면 DB 를 만지기 전에 INACTIVE.
  ② /serp 업로드 훅 — 반영(_obs_ingest)이 끝난 뒤 complete_from_upload(req.meta, status, observation_id, stop) 를 try 안에서 부른다
     (실패해도 업로드는 성공). meta.job 이 없으면 무동작(구확장 무회귀).
  ③ 표 보장 — collector 의 init 에서 init_db + purge_old 를 부른다 · main 에 router 포함 · scheduler 가 부팅 +2분·매시 05분 동기화.
  ④ 백업 안전(코덱스 이식) — 새 백업 전에 이전 세대를 미리 지우지 않고(_prune(MAX_BACKUPS - 1) 부재) · .db 단독 복사 폴백 부재 ·
     online backup 이 closing() 으로 닫히고 · 실패 시 return.
  ⑤ 정책 기본값 — env 없으면 꺼짐(INACTIVE) · 깨진 JSON 도 꺼짐 · 기본 상한 40/10/40초/깊이 300.
  ⑥ 확장 v1.24.0 — 매분 알람·수동 실행이 coordinatedEnabled() 를 거쳐 runCoordinated 로 가고 false 면 runCollection(폴백) ·
     uploadKeyword 가 meta.job 을 싣는다 · setCoordinated 명령 · 팝업 버튼. 게이트에 pacing·coord·wire·coordinated 시험 등록.
"""
import os
import re
import sys

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


def body(src, decorator_re):
    """@router… 데코레이터 다음 함수 본문(다음 @router 또는 파일 끝까지)."""
    m = re.search(decorator_re, src)
    if not m:
        return ""
    rest = src[m.end():]
    n = re.search(r"\n@router\.", rest)
    return rest[: n.start()] if n else rest


V2 = read("backend/collector_v2.py")
COL = read("backend/collector.py")
MAIN = read("backend/main.py")
SCH = read("backend/scheduler.py")
BG = read("collector-extension/background.js")
POP = read("collector-extension/popup.js")
HTML = read("collector-extension/popup.html")
MANIFEST = read("collector-extension/manifest.json")
DEPLOY = read(".github/workflows/deploy.yml")

print("① collector_v2 — 경로·인증")
ok("prefix 가 /api/collector/v2", 'prefix="/api/collector/v2"' in V2)
for ep in ("register", "claim", "report", "release"):
    b = body(V2, rf'@router\.post\("/{ep}"\)')
    ok(f"🔴 POST /{ep} 는 토큰 검사(_token(x_collector_token))가 첫 줄", bool(b) and re.search(r"\n\s+_token\(x_collector_token\)", b) is not None
       and b.index("_token(x_collector_token)") < (b.index("_conn()") if "_conn()" in b else len(b)))
for ep in ("status", "readiness"):
    b = body(V2, rf'@router\.get\("/{ep}"\)')
    ok(f"GET /{ep} 는 로그인 직원(Depends(get_current_user))", "Depends(get_current_user)" in b)
ok("🔴 readiness 는 관리자만(_admin)", "_admin(current_user)" in body(V2, r'@router\.get\("/readiness"\)'))
ok("🔴 control 은 관리자만(_admin) + 로그인", "_admin(current_user)" in body(V2, r'@router\.post\("/control"\)') and "Depends(get_current_user)" in body(V2, r'@router\.post\("/control"\)'))
ok("_admin 은 admin·superadmin 만 통과", re.search(r'role"\)\s+not in \("admin", "superadmin"\)', V2) is not None)
cb = body(V2, r'@router\.post\("/claim"\)')
ok("🔴 claim — 정책 꺼짐이면 INACTIVE 를 먼저 돌려준다(동기화·판정 전)", cb.index('"INACTIVE"') < cb.index("_maybe_sync(conn, now)") and "if not p.enabled" in cb)
ok("claim — 화면 스위치(collector_control.is_paused)를 legacy_paused 로 넘긴다", "is_paused(conn, None)" in cb and "legacy_paused=legacy_paused" in cb)
ok("claim — 기계 분할 규칙은 split_rule.split_ok 단일 원본", "from split_rule import split_ok" in cb)
ok("release 는 job 계약이 없으면 422", "job 계약이 없습니다" in body(V2, r'@router\.post\("/release"\)'))
ok("sync_today 는 유니버스·목표·슬롯 규칙을 collector 에서 가져오고 depth=policy().requested_depth", "_keyword_universe" in V2 and "_targets(conn" in V2 and "depth=policy().requested_depth" in V2)
ok("sync_today 실패는 예외를 내지 않는다(dict 로 error)", re.search(r"except Exception as e:\s*\n\s*logger\.warning\(f\"\[collector-v2\] 작업 원장 동기화 실패", V2) is not None)
ok("complete_from_upload — meta.job 없으면 None(구확장 무회귀)", re.search(r"if not job:\s*\n\s*return None", V2) is not None)
ok("complete_from_upload — 실패해도 예외를 밖으로 안 낸다", "작업 완료 처리 실패(업로드는 성공)" in V2)

print("\n② /serp 업로드 훅")
i_ing = COL.find("_obs_ingest(conn, item, today, _store_full, _project_positive)")
# 2026-09-24 완료 규칙 — 상태 자리는 「대상 다 찾으면 target_complete, 아니면 봉투 상태」(_job_status)로 바뀌었다.
i_hook = COL.find("complete_from_upload(req.meta, _job_status, item[\"observation_id\"], _stop)")
ok("🔴 반영(_obs_ingest) 뒤에 complete_from_upload(req.meta, status, observation_id, stop)", 0 < i_ing < i_hook)
ok("🔴 상태 = 대상 다 찾으면 target_complete · 아니면 봉투 상태 그대로",
   '_job_status = "target_complete" if result.get("allTargetsFound") else item["status"]' in COL[i_ing:i_hook])
seg = COL[i_ing:i_hook + 500]
ok("훅은 try 안 — 실패해도 업로드는 성공", re.search(r"try:\s*\n(\s*#[^\n]*\n)*\s*from collector_v2 import complete_from_upload", seg) is not None and "v2 작업 완료 훅 실패(업로드는 성공)" in seg)
ok("stopReason 은 봉투가 있을 때만 읽는다", 'if item.get("observation"):' in seg and 'item["observation"].get("stopReason")' in seg)
ok("결과에 job 은 additive(있을 때만)", re.search(r"if _job_out:\s*\n\s*result\[\"job\"\] = _job_out", seg) is not None)

print("\n③ 표 보장·라우터·스케줄")
ok("🔴 collector init — init_db + purge_old", "from collector_coord import init_db as _coord_init, purge_old as _coord_purge" in COL and "_coord_init(conn)" in COL and "_coord_purge(conn)" in COL)
ok("🔴 main 이 collector_v2_router 를 포함", "from collector_v2 import router as collector_v2_router" in MAIN and "app.include_router(collector_v2_router)" in MAIN)
ok("🔴 scheduler — 부팅 +2분 1회(coord_sync_boot)", re.search(r'_scheduler\.add_job\(_coord_sync_job, trigger="date", run_date=datetime\.now\(\) \+ timedelta\(minutes=2\), id="coord_sync_boot"\)', SCH) is not None)
ok("🔴 scheduler — 매시 05분(coord_sync_hourly · replace_existing)", re.search(r'_scheduler\.add_job\(_coord_sync_job, trigger="cron", minute=5, id="coord_sync_hourly", replace_existing=True\)', SCH) is not None)
ok("동기화 잡은 자기 연결을 닫고 실패를 삼킨다", re.search(r"def _coord_sync_job\(\):.*?finally:\s*\n\s*_c\.close\(\).*?except Exception as _e:\s*\n\s*logger\.warning", SCH, re.S) is not None)

print("\n④ 기동 백업 안전(코덱스 이식)")
bk_start = MAIN.find("def _backup_db_on_startup_locked")
bk_end = MAIN.find("@asynccontextmanager", bk_start)
BK = MAIN[bk_start:bk_end]
ok("🔴 새 백업 전 선정리 없음 — _prune(MAX_BACKUPS - 1) 부재", "_prune(MAX_BACKUPS - 1)" not in BK)
ok("🔴 .db 단독 복사 폴백 부재(shutil.copy2(db_path …) 없음)", re.search(r"shutil\.copy2\(\s*db_path", BK) is None)
ok("online backup 은 closing() 으로 두 연결을 닫는다", re.search(r"with closing\(sqlite3\.connect\(db_path\)\) as src, closing\(sqlite3\.connect\(backup_path\)\) as dst:\s*\n\s*src\.backup\(dst\)", BK) is not None)
ok("백업 실패면 부분 파일을 지우고 return(이전 세대 보존)", re.search(r"이전 백업 보존.*?\n\s*return", BK, re.S) is not None)
ok("최종 보관 정리(_prune(MAX_BACKUPS))는 성공한 뒤에만", BK.rfind("_prune(MAX_BACKUPS)") > BK.find("src.backup(dst)"))

print("\n⑤ 정책 기본값")
import collector_coord as cc
p0 = cc.policy_from_env({})
ok("🔴 env 없음 → 꺼짐(확장은 종전 경로)", p0.enabled is False)
ok("COLLECTOR_V2_ENABLED=1 → 켜짐", cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1"}).enabled is True)
ok("깨진 정책 JSON → 꺼짐(안전)", cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1", "COLLECTOR_V2_POLICY_JSON": "{bad"}).enabled is False)
p1 = cc.policy_from_env({"COLLECTOR_V2_ENABLED": "1", "COLLECTOR_V2_POLICY_JSON": '{"worker_hourly": 5, "unknown": 1}'})
ok("정책 JSON 은 아는 칸만 받는다", p1.worker_hourly == 5 and p1.enabled is True)
ok("기본 상한 = 전역 40/시 · 기계 10/시 · 간격 40초 · 깊이 300(HOURLY_CAP 과 같은 축)", (p0.global_hourly, p0.worker_hourly, p0.min_gap_seconds, p0.requested_depth) == (40, 10, 40, 300))

print("\n⑥ 확장 v1.24.0 배선")
ver = re.search(r'"version":\s*"(\d+)\.(\d+)\.(\d+)"', MANIFEST)
ok("manifest ≥ 1.24", ver is not None and (int(ver.group(1)), int(ver.group(2))) >= (1, 24))
ok("🔴 매분 알람 — coordinatedEnabled() 면 runCoordinated(false) · false 면 runCollection(false) 폴백",
   re.search(r"if \(await coordinatedEnabled\(\)\) \{ const handled = await runCoordinated\(false\); if \(handled\) return; \}\s*\n\s*runCollection\(false\);", BG) is not None)
ok("🔴 수동 실행(cmd run)도 같은 분기 → runCollection(true) 폴백", re.search(r"if \(await coordinatedEnabled\(\)\) \{ const handled = await runCoordinated\(true\); if \(handled\) return; \} runCollection\(true\);", BG) is not None)
ok("cmd setCoordinated 가 저장값(COORD_KEY)과 state.coordEnabled 를 함께 바꾼다", "msg?.cmd === 'setCoordinated'" in BG and "[COORD_KEY]: !!msg.on" in BG and "coordEnabled: !!msg.on" in BG)
ok("🔴 uploadKeyword(token, keyword, payload, job) 가 meta.job 을 싣는다", "async function uploadKeyword(token, keyword, payload, job)" in BG and re.search(r"job:\s*job", BG[BG.find("async function uploadKeyword("):BG.find("async function uploadKeyword(") + 6000]) is not None)
ok("v2 요청 경로는 /api/collector/v2/ + 토큰 헤더", "/api/collector/v2/${endpoint}" in BG and "'X-Collector-Token': token" in BG[BG.find("async function coordRequest("):BG.find("async function coordRequest(") + 800])
ok("404 는 NO_V2(구서버 → 종전 경로)", "code: res.status === 404 ? 'NO_V2'" in BG)
ok("🔴 막히면 markBlocked + 서버 PAUSED_BLOCK 보고 + 임대 반납(전역 정지 아님)", "await coordReport('PAUSED_BLOCK'" in BG and "state: 'PAUSED_BLOCK', reason: 'BLOCKED', job: leased" in BG)
ok("팝업 — #coordinated 버튼 + setCoordinated 메시지", 'id="coordinated"' in HTML and "cmd: 'setCoordinated'" in POP)
ok("게이트 등록 — pacing · coord · wire(이 파일) · coordinated.test.js",
   all(s in DEPLOY for s in ("backend/tests/test_collector_pacing.py", "backend/tests/test_collector_coord.py",
                             "backend/tests/test_collector_v2_wire.py", "collector-extension/tests/coordinated.test.js")))

print(f"\n{'✅' if not failed else '❌'} v2 배선 회귀 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
