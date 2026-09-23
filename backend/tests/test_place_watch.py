"""플레이스 무인 추적 멈춤 감시 — 회귀 시험 (2026-09-23)

무엇을 막는가: 9/15·9/17 에 추적기가 하루 통째로 안 돌았는데(활성 19곳 중 0곳) 아무 신호가
없었다. 쇼핑 멈춤 감시(`collect_watch`)는 쇼핑 표만 본다.

⚠️ 이 시험은 **진짜 sqlite 파일**(실제 스키마 `database.init_db`)을 만들어 실제 함수를 돌린다.
⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi 가 없다).
"""
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

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


_paths = []


def _fresh_db():
    """실제 스키마(database.init_db)로 만든 빈 DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _paths.append(path)
    os.environ["DB_PATH"] = path
    for m in ("database", "place_watch"):
        sys.modules.pop(m, None)
    import database
    database.init_db()
    import place_watch
    return path, place_watch


def _c(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _target(c, name, kw, place_id="", region="서울", active=1, created=None):
    c.execute("INSERT INTO place_track_target(business_name, region, place_id, keyword, active, created_at)"
              " VALUES(?,?,?,?,?,?)",
              (name, region, place_id, kw, active,
               created or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")))


def _rank(c, bk, kw, when, rank=None, state="노출"):
    c.execute("INSERT INTO place_rank_history(business_key, keyword, rank_position, rank_state, checked_at)"
              " VALUES(?,?,?,?,?)", (bk, kw, rank, state, when.strftime("%Y-%m-%d %H:%M:%S")))


NOW = datetime.now().replace(hour=10, minute=20, second=0, microsecond=0)
MORNING = NOW.replace(hour=6, minute=48)


def _seed19(c):
    """활성 19곳(장소번호 있음) — 9/23 실측 규모."""
    for i in range(19):
        _target(c, f"업체{i}", f"동네 맛집{i}", place_id=str(1000 + i))


# ① 키 규칙이 서버와 같다 — 갈라지면 멀쩡한 추적을 「못 쟀다」로 센다
path, pw = _fresh_db()
import place_crawler  # noqa: E402  (표준 라이브러리만 쓴다)
for s in ("미사 동 칼국수", "  Cafe  ONE ", "", None, "탭\t있음"):
    ok(f"① 정규화 규칙이 place_crawler 와 같다 — {s!r}", pw._norm(s) == place_crawler._norm(s))
main_src = _read("backend", "main.py")
_reg = main_src[main_src.index("def _place_registry_business_key"):]
_reg = _reg[:_reg.index("\n\n\n")]
ok("① ingest 키 공식이 doc:{장소번호} 그대로다", 'f"doc:{place_id}"' in _reg)
ok("① ingest 키 공식이 nm:{이름}|{지역} 그대로다", 'f"nm:{name}|{reg}"' in _reg)
ok("① 감시 키도 같은 두 공식을 낸다",
   pw.target_keys("77", "가 나", "서 울") == ["doc:77", "nm:가나|서울"])

# ② 활성 19곳 전부 오늘 잰 날 → ok
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
for i in range(19):
    _rank(c, f"doc:{1000 + i}", f"동네 맛집{i}", MORNING, rank=3 if i % 3 else None,
          state="노출" if i % 3 else "미노출")
c.commit()
ev = pw.evaluate(c, now=NOW)
ok("② 19/19 이면 ok", ev["state"] == pw.STATE_OK and ev["measured"] == 19 and ev["active"] == 19)
ok("② 미노출도 「잰 것」이다", ev["missing"] == 0 and ev["unconfirmed"] == 0)
ok("② ok 이면 문장이 없다(배너 안 띄움)", pw._message(ev) == "")

# ③ 9/15 재현 — 오늘 0곳 · 추적기 도착 기록 없음(배포 전) → missed, tracker None
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
c.commit()
ev = pw.evaluate(c, now=NOW)
ok("③ 0/19 이면 missed", ev["state"] == pw.STATE_MISSED and ev["measured"] == 0)
ok("③ 도착 기록이 한 줄도 없으면 None(= 못 잼 · 0 이 아니다)", ev["tracker"] is None)
ok("③ 문장이 PC 확인을 권한다", "전원" in pw._message(ev) and "19곳" in pw._message(ev))

# ④ 추적기는 왔는데 전부 미확인 → missed 이지만 문장이 다르다
pw.note_ingest(19, 19, 0, conn=c)
for i in range(19):
    _rank(c, f"doc:{1000 + i}", f"동네 맛집{i}", MORNING, rank=None, state="미확인")
c.commit()
ev = pw.evaluate(c, now=NOW)
ok("④ 미확인은 「잰 것」이 아니다", ev["state"] == pw.STATE_MISSED and ev["unconfirmed"] == 19)
ok("④ 도착 1회가 보인다", ev["tracker"] is not None and ev["tracker"]["arrivals"] == 1)
ok("④ 문장이 「돌았지만 읽지 못했다」로 갈린다", "읽지 못했습니다" in pw._message(ev))

# ⑤ 09시 전에는 판정하지 않는다(추적기가 아직 도는 중일 수 있다)
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
c.commit()
ev = pw.evaluate(c, now=NOW.replace(hour=8, minute=59))
ok("⑤ 08:59 에 0곳이면 pending(경보 아님)", ev["state"] == pw.STATE_PENDING)
ok("⑤ pending 은 문장이 없다", pw._message(ev) == "")
for i in range(19):
    _rank(c, f"doc:{1000 + i}", f"동네 맛집{i}", NOW.replace(hour=6, minute=40), rank=1)
c.commit()
ok("⑤ 판정 시각 전이라도 다 쟀으면 ok",
   pw.evaluate(c, now=NOW.replace(hour=7))["state"] == pw.STATE_OK)

# ⑥ 9/16~9/21 재현 — 18/19 · 한 곳이 사흘째 빠짐 → partial + stale 1
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
_target(c, "새업체", "새 키워드", place_id="9999",
        created=(NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"))
for d in range(3):
    day = MORNING - timedelta(days=d)
    for i in range(18):                       # 업체18 은 사흘 내내 빠진다
        _rank(c, f"doc:{1000 + i}", f"동네 맛집{i}", day, rank=5)
c.commit()
ev = pw.evaluate(c, now=NOW)
ok("⑥ 18/20 이면 partial", ev["state"] == pw.STATE_PARTIAL and ev["measured"] == 18 and ev["active"] == 20)
ok("⑥ 사흘째 못 잰 곳 1(어제 등록한 곳은 빼고)", ev["stale"] == 1 and ev["stale_ids"] and len(ev["stale_ids"]) == 1)
ok("⑥ 문장에 사흘째가 나온다", "3일째" in pw._message(ev))
ok("⑥ 문장에 업체명·키워드가 없다", "업체" not in pw._message(ev) and "맛집" not in pw._message(ev))

# ⑦ 같은 날 실측이 있으면 미확인보다 이긴다(save_place_rank 규칙과 같다)
path, pw = _fresh_db()
c = _c(path)
_target(c, "하나", "칼국수", place_id="1")
_rank(c, "doc:1", "칼국수", MORNING, rank=None, state="미확인")
_rank(c, "doc:1", "칼국수", MORNING.replace(hour=9), rank=7)
c.commit()
ok("⑦ 미확인+실측이 섞이면 잰 것", pw.evaluate(c, now=NOW)["state"] == pw.STATE_OK)

# ⑧ 장소번호가 있어도 그날 nm: 로 남은 기록을 센다(self-heal 전 기록 · 직원 분석)
path, pw = _fresh_db()
c = _c(path)
_target(c, "미사 칼국수", "미사동 칼국수", place_id="555", region="하남 미사")
_rank(c, "nm:미사칼국수|하남미사", "미사동 칼국수", MORNING, rank=2)
c.commit()
ok("⑧ nm: 키 기록도 잡는다", pw.evaluate(c, now=NOW)["state"] == pw.STATE_OK)

# ⑨ 키워드 앞뒤 공백은 같게 본다(추적기가 trim 해서 보낸다)
path, pw = _fresh_db()
c = _c(path)
_target(c, "둘", " 성수 카페 ", place_id="2")
_rank(c, "doc:2", "성수 카페", MORNING, rank=1)
c.commit()
ok("⑨ 키워드 앞뒤 공백 무시", pw.evaluate(c, now=NOW)["state"] == pw.STATE_OK)

# ⑩ 꺼진 대상은 세지 않는다 · 대상이 없으면 none(경보 아님)
path, pw = _fresh_db()
c = _c(path)
_target(c, "셋", "꺼진 키워드", place_id="3", active=0)
c.commit()
ev = pw.evaluate(c, now=NOW)
ok("⑩ 활성 0 이면 none", ev["state"] == pw.STATE_NONE and ev["active"] == 0)
ok("⑩ none 은 문장이 없다", pw._message(ev) == "")

# ⑪ 알림은 새로 생길 때만 — 같은 날 같은 상태가 이어지면 조용하다(로그 도배 방지)
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
c.commit()
r1 = pw.run_check(conn=c, now=NOW)
c.commit()
r2 = pw.run_check(conn=c, now=NOW + timedelta(hours=1))
c.commit()
ok("⑪ 오늘 첫 missed 는 알린다", r1["notice"] == pw.STATE_MISSED)
ok("⑪ 한 시간 뒤 같은 상태는 조용하다", r2["notice"] is None)
for i in range(19):
    _rank(c, f"doc:{1000 + i}", f"동네 맛집{i}", NOW + timedelta(hours=1, minutes=30), rank=4)
c.commit()
r3 = pw.run_check(conn=c, now=NOW + timedelta(hours=2))
c.commit()
ok("⑪ 같은 날 다 재면 recovered 한 번", r3["notice"] == "recovered")
r4 = pw.run_check(conn=c, now=NOW + timedelta(hours=3))
ok("⑪ 그 뒤는 조용하다", r4["notice"] is None)
r5 = pw.run_check(conn=c, now=NOW + timedelta(days=1))
ok("⑪ 다음 날 또 못 재면 다시 알린다", r5["notice"] == pw.STATE_MISSED)

# ⑫ 자기 연결로 돌면 판정이 **실제로 커밋**된다(collect_watch 교훈 — 안 되면 매시간 같은 알림)
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
c.commit()
c.close()
pw.run_check(now=NOW)
n = _c(path).execute("SELECT COUNT(*) n FROM place_watch").fetchone()["n"]
ok("⑫ run_check 가 남긴 줄이 다른 연결에서 보인다", n == 1)
pw.note_ingest(3, 2, 1)
n = _c(path).execute("SELECT COUNT(*) n FROM place_ingest_seen").fetchone()["n"]
ok("⑫ note_ingest 도 커밋된다", n == 1)

# ⑬ 어떤 실패도 밖으로 안 나간다
os.environ["DB_PATH"] = os.path.dirname(path)      # 디렉터리 = 열 수 없는 DB
sys.modules.pop("place_watch", None)
import place_watch as pw_bad  # noqa: E402
try:
    r = pw_bad.note_ingest(1, 1, 0)
    ok("⑬ note_ingest 실패는 False 로 끝난다", r is False)
    r = pw_bad.run_check(now=NOW)
    ok("⑬ run_check 실패는 unknown 으로 끝난다", r.get("state") == pw_bad.STATE_UNKNOWN)
    ok("⑬ summary 실패는 빈 dict(= 못 쟀다)", pw_bad.summary(now=NOW) == {})
except Exception as e:  # pragma: no cover
    ok(f"⑬ 예외가 새어 나왔다: {e}", False)

# ⑭ 표가 없으면 unknown — 「0곳」으로 찍지 않는다
fd, bare = tempfile.mkstemp(suffix=".db")
os.close(fd)
_paths.append(bare)
os.environ["DB_PATH"] = bare
sys.modules.pop("place_watch", None)
import place_watch as pw_bare  # noqa: E402
ev = pw_bare.evaluate(_c(bare), now=NOW)
ok("⑭ 추적 표가 없으면 unknown", ev["state"] == pw_bare.STATE_UNKNOWN and ev["measured"] is None)
ok("⑭ unknown 이면 summary 는 빈 dict", pw_bare.summary(now=NOW) == {})

# ⑮ 지난 14일 줄 — 빠진 날은 0, 등록 전 날은 분모에서 뺀다
path, pw = _fresh_db()
c = _c(path)
_seed19(c)
_target(c, "늦게", "늦은 키워드", place_id="8888",
        created=(NOW - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"))
for d in range(14):
    if d in (8, 6):                           # 9/15·9/17 같은 날
        continue
    for i in range(19):
        _rank(c, f"doc:{1000 + i}", f"동네 맛집{i}", MORNING - timedelta(days=d), rank=2)
c.commit()
days = pw.history(c, now=NOW)
ok("⑮ 14일치", days is not None and len(days) == 14)
ok("⑮ 빠진 날은 0", days[14 - 1 - 8]["measured"] == 0 and days[14 - 1 - 6]["measured"] == 0)
ok("⑮ 등록 전 날은 분모가 19", days[0]["active"] == 19)
ok("⑮ 등록 뒤 날은 분모가 20", days[-1]["active"] == 20)
s = pw.summary(conn=c, now=NOW)
ok("⑮ summary 에 날짜별 줄이 실린다", isinstance(s.get("days"), list) and len(s["days"]) == 14)

# ⑯ 오래된 감시 기록은 정리한다(무한히 쌓이지 않게)
path, pw = _fresh_db()
c = _c(path)
pw.ensure_table(c)
old = (NOW - timedelta(days=pw.KEEP_DAYS + 5)).strftime("%Y-%m-%d %H:%M:%S")
c.execute("INSERT INTO place_watch(checked_at, state) VALUES(?, 'ok')", (old,))
c.execute("INSERT INTO place_ingest_seen(received_at) VALUES(?)", (old,))
c.commit()
pw.run_check(conn=c, now=NOW)
c.commit()
ok("⑯ 보관 기한 지난 감시 줄은 지운다",
   c.execute("SELECT COUNT(*) n FROM place_watch WHERE checked_at=?", (old,)).fetchone()["n"] == 0)
ok("⑯ 보관 기한 지난 도착 줄도 지운다",
   c.execute("SELECT COUNT(*) n FROM place_ingest_seen").fetchone()["n"] == 0)

# ⑰ 배선 — 도착 기록 · 스케줄 · 화면 응답
_ing = main_src[main_src.index('@app.post("/api/place/ingest")'):]
_ing = _ing[:_ing.index('@app.post("/api/seo/analyze")')]
ok("⑰ ingest 가 도착을 적는다", "note_ingest" in _ing and "_pw_note(len(req.results or []), saved, skipped)" in _ing)
ok("⑰ 도착 기록 실패가 응답을 깨지 않는다(try 안)",
   _ing.index("try:\n            from place_watch") < _ing.index("_pw_note(len("))
sch = _read("backend", "scheduler.py")
m = re.search(r"_run_place_watch,\s*trigger=CronTrigger\(hour=\"9-21\", minute=20\)", sch)
ok("⑰ 스케줄이 09~21시 매시 20분이다", bool(m))
ok("⑰ 스케줄 잡이 실제 함수를 부른다", "def _run_place_watch():" in sch and "place_watch.run_check()" in sch)
col = _read("backend", "collector.py")
ok("⑰ /api/collector/health 가 place 를 싣는다", '"place": place}' in col and "_pw_summary()" in col)
ok("⑰ 기존 쇼핑 state 판정은 그대로다", 'state, msg = "ok", ""' in col)

# ⑱ 판정 시각이 추적기 시각보다 뒤다 — 추적기를 늦추면 멀쩡한 날에 경보가 울린다
pw_src = _read("backend", "place_watch.py")
ok("⑱ 기본 판정 시각 9시", '"PLACE_WATCH_FROM_HOUR", 9' in pw_src)
ok("⑱ 기본 사흘", '"PLACE_WATCH_STALE_DAYS", 3' in pw_src)
runner = _read("extension-place", "place-runner.js")
mh = re.search(r"var RUN_HOUR = (\d+), RUN_MIN = (\d+);", runner)
ok("⑱ 추적기 시각을 읽었다", bool(mh))
if mh:
    ok("⑱ 추적기(06:30)가 판정 시각보다 2시간 이상 앞선다",
       int(mh.group(1)) * 60 + int(mh.group(2)) + 120 <= 9 * 60)

# ⑲ 공개 로그에 이름을 흘리지 않는다
_job = sch[sch.index("def _run_place_watch():"):]
_job = _job[:_job.index("\n\n\n")]
ok("⑲ 스케줄 로그가 업체명·키워드를 안 찍는다",
   "business_name" not in _job and "keyword" not in _job)
ok("⑲ 도착 기록이 업체명·키워드를 안 받는다",
   "def note_ingest(items: int, saved: int, skipped: int" in pw_src)

for p in _paths:
    try:
        os.unlink(p)
    except OSError:
        pass

print(f"\n{'❌ 실패 %d건 / 전체 %d' % (_fail, _pass + _fail) if _fail else '플레이스 추적 멈춤 감시 시험 전부 통과'}")
sys.exit(1 if _fail else 0)
