"""수집 멈춤 감시 — 회귀 시험 (2026-09-10)

무엇을 막는가: 2026-09-10 에 수집이 **하루 통째로 0건**이 됐는데 아무도 몰랐다.
서비스는 멀쩡히 돌고 화면은 어제 순위를 그대로 보여 줬다.

⚠️ 이 시험은 **진짜 sqlite 파일**을 만들어 실제 함수를 돌린다 — 로직 재현이 아니다.
⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi 가 없다).
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

_pass = _fail = 0


def ok(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}")


def _fresh_db(last_upload_hours_ago=None):
    """collected_serp 한 표만 있는 임시 DB. 마지막 업로드 시각을 원하는 대로 심는다."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE collected_serp(
        id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT, collected_date TEXT,
        products_json TEXT, product_count INTEGER, created_at TEXT)""")
    if last_upload_hours_ago is not None:
        t = datetime.now() - timedelta(hours=last_upload_hours_ago)
        conn.execute("INSERT INTO collected_serp(keyword, collected_date, products_json,"
                     " product_count, created_at) VALUES('김치','2026-09-10','[]',0,?)",
                     (t.strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()
    conn.close()
    return path


def _mod(db_path, gap=None, cooldown=None):
    """환경변수를 세팅한 채로 모듈을 새로 읽어 온다(상수를 import 시점에 굳히므로)."""
    os.environ["DB_PATH"] = db_path
    if gap is not None:
        os.environ["COLLECT_ALERT_GAP_HOURS"] = str(gap)
    if cooldown is not None:
        os.environ["COLLECT_ALERT_COOLDOWN_HOURS"] = str(cooldown)
    for m in ("collect_watch",):
        sys.modules.pop(m, None)
    import collect_watch
    return collect_watch


print("\n[수집 멈춤 감시]")

# ① 정상 — 방금 올라왔으면 아무 일도 없다
db = _fresh_db(last_upload_hours_ago=0.5)
cw = _mod(db)
sent = []
r = cw.run_check(send=lambda t: sent.append(t) or True)
ok("① 30분 전 업로드면 정상으로 본다", r["state"] == cw.STATE_OK)
ok("① 정상일 때는 아무것도 안 보낸다", sent == [] and r["notice"] is None)

# ② 멈춤 — 상한을 넘기면 알린다
db = _fresh_db(last_upload_hours_ago=7)
cw = _mod(db)
sent = []
r = cw.run_check(send=lambda t: sent.append(t) or True)
ok("② 7시간 조용하면 멈춤으로 본다", r["state"] == cw.STATE_QUIET)
ok("② 알림을 한 번 보낸다", len(sent) == 1 and r["sent"] is True)
ok("② 문자에 몇 시간인지 적는다", "7시간" in sent[0])
ok("② 문자에 무엇을 할지 적는다", "맥미니" in sent[0])
ok("② SMS 90바이트 안에 들어간다", len(sent[0].encode("utf-8")) <= 90)

# ③ 도배 방지 — 계속 조용해도 쿨다운 전에는 다시 안 보낸다
sent2 = []
r2 = cw.run_check(send=lambda t: sent2.append(t) or True)
ok("③ 이어지는 점검에서는 다시 안 보낸다", sent2 == [] and r2["notice"] is None)
ok("③ 그래도 상태 기록은 계속 쌓는다",
   sqlite3.connect(db).execute("SELECT COUNT(*) FROM collect_watch").fetchone()[0] == 2)

# ④ 쿨다운이 지나면 다시 보낸다
cw2 = _mod(db, cooldown=1)
conn = sqlite3.connect(db)
old = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
conn.execute("UPDATE collect_watch SET checked_at=? WHERE notified=1", (old,))
conn.commit()
conn.close()
sent3 = []
cw2.run_check(send=lambda t: sent3.append(t) or True)
ok("④ 쿨다운이 지나면 다시 알린다", len(sent3) == 1)

# ⑤ 복구 — 돌아오면 한 번 알린다. 그 다음부터는 조용하다
conn = sqlite3.connect(db)
conn.execute("UPDATE collected_serp SET created_at=?",
             (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
conn.commit()
conn.close()
sent4 = []
r4 = cw2.run_check(send=lambda t: sent4.append(t) or True)
ok("⑤ 돌아오면 복구를 알린다", r4["notice"] == "recovered" and len(sent4) == 1)
ok("⑤ 복구 문자에는 시간이 안 들어간다(그럴 필요가 없다)", "시간째" not in sent4[0])
sent5 = []
r5 = cw2.run_check(send=lambda t: sent5.append(t) or True)
ok("⑤ 그 뒤에는 조용하다", sent5 == [] and r5["notice"] is None)

# ⑥ 데이터가 아예 없을 때 — 「멈췄다」로 단정하지 않는다
db2 = _fresh_db(last_upload_hours_ago=None)
cw3 = _mod(db2)
sent6 = []
r6 = cw3.run_check(send=lambda t: sent6.append(t) or True)
ok("⑥ 업로드 이력이 없으면 판정 보류", r6["state"] == cw3.STATE_UNKNOWN)
ok("⑥ 그때는 알리지 않는다", sent6 == [])

# ⑦ 문자를 못 보내도 서버는 안 죽고, 기록은 남는다
db3 = _fresh_db(last_upload_hours_ago=9)
cw4 = _mod(db3)


def _boom(_t):
    raise RuntimeError("문자 서버 장애")


r7 = cw4.run_check(send=_boom)
ok("⑦ 발송이 터져도 예외가 밖으로 안 나온다", r7["state"] == cw4.STATE_QUIET)
ok("⑦ 못 보낸 것으로 기록한다", r7["sent"] is False)
row = sqlite3.connect(db3).execute(
    "SELECT notified, note FROM collect_watch ORDER BY id DESC LIMIT 1").fetchone()
ok("⑦ 못 나간 것은 보낸 것으로 세지 않는다", row[0] == 0 and "nosend" in row[1])

# ⑦-2 못 보낸 판정이 **쿨다운을 걸지 않는다** — 번호를 나중에 넣어도 그날 문자가 오게.
#     ⚠️ 이걸 안 지키면 「경보를 켜 둔 날 저녁에는 확인할 수 없다」가 된다(2026-09-10 실측).
sent7 = []
r7b = cw4.run_check(send=lambda t: sent7.append(t) or True)
ok("⑦-2 못 보낸 뒤 다음 점검에서는 실제로 보낸다", len(sent7) == 1)
row = sqlite3.connect(db3).execute(
    "SELECT notified FROM collect_watch ORDER BY id DESC LIMIT 1").fetchone()
ok("⑦-2 그때는 보낸 것으로 남는다", row[0] == 1)

# ⑧ send 를 안 주면(설정 없음) 조용히 기록만 한다
db4 = _fresh_db(last_upload_hours_ago=9)
cw5 = _mod(db4)
r8 = cw5.run_check(send=None)
ok("⑧ 보낼 곳이 없어도 판정과 기록은 한다", r8["state"] == cw5.STATE_QUIET and r8["sent"] is False)

# ⑨ 상한 값이 살아 있다 — 아무도 몰래 100시간으로 늘려 놓으면 경보가 무의미해진다
src = open(os.path.join(os.path.dirname(HERE), "collect_watch.py"), encoding="utf-8").read()
ok("⑨ 기본 상한이 5시간이다", '"COLLECT_ALERT_GAP_HOURS", 5' in src)
ok("⑨ 기본 쿨다운이 6시간이다", '"COLLECT_ALERT_COOLDOWN_HOURS", 6' in src)
ok("⑨ 요청이 아니라 업로드로 잰다", "collected_serp" in src and "/api/collector/health" not in src.split("⚠️")[0])

# ⑩ 시계가 어긋나 음수가 나와도 경보를 울리지 않는다
db5 = _fresh_db(last_upload_hours_ago=-3)
cw6 = _mod(db5)
r10 = cw6.run_check(send=None)
ok("⑩ 미래 시각이면 방금 올라온 것으로 본다", r10["state"] == cw6.STATE_OK)

for p in (db, db2, db3, db4, db5):
    try:
        os.unlink(p)
    except OSError:
        pass

print(f"\n{'❌ 실패 %d건 / 전체 %d' % (_fail, _pass + _fail) if _fail else '수집 멈춤 감시 시험 전부 통과'}")
sys.exit(1 if _fail else 0)
