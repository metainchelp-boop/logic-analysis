"""아침 분석 이어서 하기(2026-11-17 · 대표 「고쳐」) 회귀.

11/3 · 11/4 · 11/15 · 11/16 아침 분석이 시작 20초 안에 1~4건만 하고 멈췄고 그날 다시 돌지 않았다.
  ① 진행 기록(daily_batch_runs) — 시작 · 키워드마다 · 끝 · 일꾼 번호
  ② 오전 점검(08:35~10:59 · 10분마다) — 끊겼으면 남은 키워드만 이어서 · 시작 안 됐으면 시작
  ③ 11시 이후 · 하루 3번 넘게는 하지 않음 · 같은 일꾼에서 도는 중이면 새로 돌리지 않음
를 지키는지 본다.

외부 네트워크 0 · 실제 DB 0(임시 파일). 스케줄러를 실제로 불러 보는 묶음은 apscheduler 가 있을 때만 돈다
(배포 회귀 게이트에는 없어 그 묶음만 건너뛰고 규칙 · 소스로 확인한다).
"""
import os
import re
import sys
import types
import socket
import sqlite3
import tempfile
from datetime import datetime, date, time as dtime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("JWT_SECRET_KEY", "offline-daily-batch-test-only")

_real_connect = socket.socket.connect
def _no_net(self, addr):
    raise AssertionError(f"외부 연결 금지: {addr}")
socket.socket.connect = _no_net

passed = failed = skipped = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {extra}")

def read(p):
    return Path(p).read_text(encoding="utf-8")

import daily_batch_state as dbs

TODAY = date.today()
def at(h, m, s=0):
    return datetime.combine(TODAY, dtime(h, m, s))
def ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# ── ① 기록 ──
c = sqlite3.connect(":memory:")
dbs.ensure_table(c)
d = TODAY.isoformat()
dbs.mark_start(c, d, 111, now=at(8, 30))
dbs.set_total(c, d, 10, 0)
dbs.heartbeat(c, d, 29, True, now=at(8, 30, 5))
dbs.heartbeat(c, d, 30, False, now=at(8, 30, 9))
r = dbs.get_run(c, d)
check("기록 · 시작 · 진행 · 마지막 업체 · 일꾼 번호",
      r["started_at"] == ts(at(8, 30)) and r["heartbeat_at"] == ts(at(8, 30, 9)) and r["done"] == 1
      and r["failed"] == 1 and r["last_client_id"] == 30 and r["pid"] == 111 and r["finished_at"] is None, r)
dbs.mark_start(c, d, 222, resume=True, now=at(8, 45))
r = dbs.get_run(c, d)
check("기록 · 이어서 하기는 진행 수를 두고 횟수만 늘린다 · 직전 일꾼을 메모에",
      r["done"] == 1 and r["resumes"] == 1 and r["pid"] == 222 and "직전 일꾼 111" in (r["note"] or "")
      and "마지막 갱신 08:30:09" in (r["note"] or ""), r)
dbs.mark_finish(c, d, now=at(9, 40))
check("기록 · 끝", dbs.get_run(c, d)["finished_at"] == ts(at(9, 40)))
dbs.add_note(c, d, "전체 분석 실패 — 시험")
check("기록 · 실패 메모는 덧붙인다(앞 메모 유지)", "직전 일꾼 111" in dbs.get_run(c, d)["note"]
      and "전체 분석 실패" in dbs.get_run(c, d)["note"])
c.close()

# ── ② ③ 판단 ──
def row(hb=None, finished=None, resumes=0):
    return {"started_at": ts(at(8, 30)), "heartbeat_at": ts(hb or at(8, 30, 20)), "finished_at": finished,
            "resumes": resumes, "done": 2}
check("판단 · 끊김(3분 넘게 멈춤)이면 이어서", dbs.decide(row(), at(8, 45)) == "resume")
check("판단 · 아직 진행 중(갱신 1분 전)이면 아무것도 안 함", dbs.decide(row(hb=at(8, 44)), at(8, 45)) is None)
check("판단 · 끝났으면 아무것도 안 함", dbs.decide(row(finished=ts(at(9, 40))), at(9, 45)) is None)
check("판단 · 오늘 기록이 없으면 시작", dbs.decide(None, at(8, 45)) == "start")
check("판단 · 이어서 하기 3번이 넘으면 멈춤(같은 자리에서 계속 죽는 경우)",
      dbs.decide(row(resumes=3), at(10, 15)) is None and dbs.decide(row(resumes=2), at(10, 15)) == "resume")
check("판단 · 08:35 전에는 안 함(08:30 정규 시작과 겹침 방지)",
      dbs.decide(None, at(8, 34)) is None and dbs.decide(row(), at(8, 34, 59)) is None)
check("판단 · 11시부터는 안 함(업무 시간 부하)",
      dbs.decide(row(), at(11, 0)) is None and dbs.decide(None, at(14, 0)) is None and dbs.decide(row(), at(10, 59)) == "resume")
check("판단 · 같은 일꾼에서 도는 중 · 진행 멈춤이면 「붙잡힘」만 알림(새로 안 돌림)",
      dbs.decide(row(), at(8, 45), running_here=True) == "stuck")
check("판단 · 같은 일꾼에서 도는 중 · 진행 중이면 아무것도 안 함",
      dbs.decide(row(hb=at(8, 44)), at(8, 45), running_here=True) is None)
check("판단 · 기록 시각이 깨져 있으면 끊김으로 봄", dbs.decide({"heartbeat_at": "x", "started_at": "x",
      "finished_at": None, "resumes": 0}, at(9, 0)) == "resume")
check("규칙 파일 · 표준 라이브러리만", not re.search(r"^\s*(import|from)\s+(apscheduler|fastapi|anthropic|requests)",
      read(BACKEND / "daily_batch_state.py"), re.M))

# ── 소스 ──
sc = read(BACKEND / "scheduler.py")
check("스케줄러 · 오전 점검 등록(8~10시 · 5분 단위)",
      'CronTrigger(hour="8-10", minute="5,15,25,35,45,55")' in sc and "_watch_daily_analysis," in sc
      and 'id="daily_analysis_watch"' in sc)
check("스케줄러 · 키워드 성공 · 실패 둘 다 진행 기록",
      "_batch_state(_dbs.heartbeat, _st, today, cid, True)" in sc and "_batch_state(_dbs.heartbeat, _st, today, cid, False)" in sc)
check("스케줄러 · 끝 기록", sc.count("_batch_state(_dbs.mark_finish, _st, today)") >= 2)
check("스케줄러 · 이어서 하기는 오늘 분석한 업체 · 키워드를 건너뜀",
      "SELECT client_id, keyword FROM client_analyses WHERE analyzed_date = ?" in sc)
check("스케줄러 · 같은 일꾼 안 겹침 잠금", "_daily_analysis_lock.acquire(blocking=False)" in sc)
check("스케줄러 · 08:30 정규 잡은 그대로", 'trigger=CronTrigger(hour=8, minute=30),\n        id="daily_analysis",' in sc)
dy = read(ROOT / ".github" / "workflows" / "deploy.yml")
check("배포 · 이 시험이 게이트에 등록됨", "test_daily_batch_resume.py" in dy)

import py_compile
try:
    py_compile.compile(str(BACKEND / "scheduler.py"), doraise=True)
    _compiled = True
except py_compile.PyCompileError as e:
    _compiled = False
    print(e)
check("스케줄러 · 문법 오류 없음(게이트에서도 확인)", _compiled)

# ── 실제 실행(apscheduler 가 있을 때만) ──
# ⚠️ 의존성이 없을 때만 건너뛴다 — scheduler 를 불러오다 나는 오류(문법 등)는 건너뛰지 않고 실패로 둔다.
try:
    import apscheduler  # noqa: F401
    _have_sched = True
except ImportError as e:
    _have_sched = False
    skipped += 1
    print(f"  SKIP  스케줄러 실제 실행 — 의존성 없음({type(e).__name__})")
if _have_sched:
    import scheduler as sch
    class _Crash(BaseException):
        """일꾼이 죽는 것 흉내 — 분석 안의 except Exception 에 잡히지 않는다."""

    calls = []
    plan = {"crash_at": None}

    def _fake_run_single_analysis(client_id, client_name, keyword, product_url="", **kw):
        calls.append((client_id, keyword))
        if plan["crash_at"] is not None and len(calls) == plan["crash_at"]:
            raise _Crash("일꾼 죽음")
        cc = sqlite3.connect(os.environ["DB_PATH"])
        cc.execute("INSERT INTO client_analyses (client_id, keyword, analyzed_date) VALUES (?, ?, ?)",
                   (client_id, keyword, TODAY.isoformat()))
        cc.commit(); cc.close()
        return {}

    fake_aa = types.ModuleType("auto_analysis")
    fake_aa.run_single_analysis = _fake_run_single_analysis
    fake_aa.get_related_keywords = lambda kw: {}
    fake_nc = types.ModuleType("naver_crawler")
    fake_nc.search_naver_shopping_api = lambda kw, display=100, enqueue_on_miss=False: {"items": [], "total": 0}
    fake_nc._parse_api_item = lambda item, i: {}
    fake_nc.get_keyword_volume = lambda kws: [{}]
    fake_cd = types.ModuleType("client_dashboard")
    fake_cd.cleanup_expired_competitors = lambda: 0

    saved_mods = {k: sys.modules.get(k) for k in ("auto_analysis", "naver_crawler", "client_dashboard")}
    sys.modules.update({"auto_analysis": fake_aa, "naver_crawler": fake_nc, "client_dashboard": fake_cd})
    orig_sql, orig_sleep = sch.eligible_clients_sql, sch.time.sleep
    sch.eligible_clients_sql = lambda cols: f"SELECT {cols} FROM clients"
    sch.time.sleep = lambda s: None
    orig_db = os.environ.get("DB_PATH")
    tmp = tempfile.mkdtemp()

    def _fresh_db(name):
        p = os.path.join(tmp, name)
        cc = sqlite3.connect(p)
        cc.executescript("""
            CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT, main_keywords TEXT, naver_store_url TEXT);
            CREATE TABLE client_analyses (client_id INTEGER, keyword TEXT, analyzed_date TEXT);
        """)
        cc.executemany("INSERT INTO clients VALUES (?, ?, ?, ?)", [
            (29, "가", "a1,a2,a3", "u"), (30, "나", "b1,b2", "u"), (31, "다", "c1,c2,c3", "u")])
        cc.commit(); cc.close()
        os.environ["DB_PATH"] = p
        return p

    def _row(p):
        cc = sqlite3.connect(p)
        try:
            return dbs.get_run(cc, TODAY.isoformat())
        finally:
            cc.close()

    def _set_hb(p, when):
        cc = sqlite3.connect(p)
        cc.execute("UPDATE daily_batch_runs SET heartbeat_at=? WHERE run_date=?", (ts(when), TODAY.isoformat()))
        cc.commit(); cc.close()

    try:
        # 1) 정규 실행이 3번째 키워드에서 죽는다 → 오전 점검이 남은 6건만 이어서 한다
        p = _fresh_db("a.db")
        plan["crash_at"] = 3
        try:
            sch._run_daily_analysis()
            died = False
        except _Crash:
            died = True
        r1 = _row(p)
        check("실행 · 일꾼이 죽으면 기록은 「시작 · 끝나지 않음 · 2건」으로 남는다",
              died and r1 and r1["finished_at"] is None and r1["done"] == 2 and r1["total"] == 8, r1)
        check("실행 · 죽어도 같은 일꾼 잠금은 풀린다", not sch._daily_analysis_lock.locked())

        plan["crash_at"] = None
        calls.clear()
        _set_hb(p, at(8, 30, 20))
        act = sch._watch_daily_analysis(now=at(8, 45))
        r2 = _row(p)
        check("실행 · 08:45 점검이 이어서 한다", act == "resume", act)
        check("실행 · 이어서 하기는 남은 6건만(이미 한 2건은 다시 안 함)",
              len(calls) == 6 and len(set(calls)) == 6, calls)
        check("실행 · 이어서 한 뒤 기록은 끝 · 8건 · 1회차 · 건너뜀 2",
              r2["finished_at"] is not None and r2["done"] == 8 and r2["resumes"] == 1 and r2["skipped"] == 2, r2)
        cc = sqlite3.connect(p)
        n = cc.execute("SELECT COUNT(*), COUNT(DISTINCT client_id || ':' || keyword) FROM client_analyses").fetchone()
        cc.close()
        check("실행 · 오늘 분석 결과는 업체 · 키워드마다 한 번씩 8건", n == (8, 8), n)
        calls.clear()
        check("실행 · 끝난 날 다음 점검은 아무것도 안 함",
              sch._watch_daily_analysis(now=at(8, 55)) is None and not calls)

        # 2) 08:30 에 시작조차 못 한 날 — 예전 코드가 이미 3건 분석해 둔 상태에서 점검이 시작한다
        p = _fresh_db("b.db")
        cc = sqlite3.connect(p)
        cc.executemany("INSERT INTO client_analyses VALUES (?, ?, ?)",
                       [(29, "a1", TODAY.isoformat()), (29, "a2", TODAY.isoformat()), (30, "b1", TODAY.isoformat())])
        cc.commit(); cc.close()
        calls.clear()
        act = sch._watch_daily_analysis(now=at(9, 5))
        r3 = _row(p)
        check("실행 · 시작 안 된 날은 점검이 시작 · 이미 분석한 3건은 건너뜀",
              act == "start" and len(calls) == 5 and (29, "a1") not in calls and r3["finished_at"]
              and "08:30 에 시작 안 됨" in (r3["note"] or "") and r3["skipped"] == 3, (act, calls, r3))
        calls.clear()
        check("실행 · 11시 뒤에는 시작 안 된 날이라도 안 함",
              _fresh_db("c.db") and sch._watch_daily_analysis(now=at(11, 5)) is None and not calls)

        # 3) 같은 일꾼에서 도는 중이면 새로 안 돌린다
        p = _fresh_db("d.db")
        sch._daily_analysis_lock.acquire()
        try:
            calls.clear()
            sch._run_daily_analysis()
            check("실행 · 같은 일꾼에서 도는 중이면 정규 실행도 건너뜀", not calls)
            cc = sqlite3.connect(p); dbs.ensure_table(cc)
            dbs.mark_start(cc, TODAY.isoformat(), 1, now=at(8, 30)); cc.close()
            act = sch._watch_daily_analysis(now=at(9, 0))
            check("실행 · 붙잡힌 채 멈추면 「stuck」 알림만(새로 안 돌림)", act == "stuck" and not calls, (act, calls))
        finally:
            sch._daily_analysis_lock.release()
    finally:
        sch.eligible_clients_sql, sch.time.sleep = orig_sql, orig_sleep
        for k, v in saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        if orig_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = orig_db

socket.socket.connect = _real_connect
print(f"\n결과: {passed} 통과 · {failed} 실패 · {skipped} 건너뜀")
sys.exit(1 if failed else 0)
