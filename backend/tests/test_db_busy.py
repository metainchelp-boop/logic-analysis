"""회귀 — 짧은 쓰기(📡 heartbeat · 🧱 막힘 보고)가 배치 잠금에 밀려 500 으로 죽지 않게 (2026-09-23)

지키는 것:
  ① db_busy.write_with_retry — 잠금이 풀리면 성공한다 · 잠금 외 오류는 그대로 올린다(삼키지 않는다) ·
     재시도를 다 쓰면 DbBusy · 재시도 사이에 backoff 로 쉰다 · 기본값(30초 · 3회)이 낡지 않았다.
  ② 서버 배선 — POST /heartbeat · POST /blocked 가 write_with_retry 를 쓰고 DbBusy 를 503 으로 바꾼다
     (종전 `sqlite3.connect(DB_PATH, timeout=10)` 직접 연결이 그 두 핸들러에 남아 있지 않다).

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없다. ①은 실제 모듈을 임시 파일 DB 로, ②는 소스 배선으로.
"""
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time

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


import db_busy

print("① db_busy.write_with_retry — 임시 파일 DB")
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "t.db")
c0 = sqlite3.connect(path)
c0.execute("CREATE TABLE t(v TEXT)")
c0.commit(); c0.close()


def hold_lock(seconds):
    """다른 연결이 쓰기 잠금을 seconds 동안 쥔다(배치 흉내)."""
    c = sqlite3.connect(path, timeout=0.1)
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO t VALUES('batch')")
    time.sleep(seconds)
    c.commit(); c.close()


def ins(conn):
    conn.execute("INSERT INTO t VALUES('hb')")
    conn.commit()
    return "stored"


# 잠금 1.2초 · 연결 timeout 0.2초 · 3회 · backoff 0.5 → 두 번째나 세 번째 시도에서 풀린다
t = threading.Thread(target=hold_lock, args=(1.2,)); t.start(); time.sleep(0.1)
slept = []
r = db_busy.write_with_retry(path, ins, tries=3, backoff=0.5, timeout=0.2, sleep=lambda s: (slept.append(s), time.sleep(s)))
t.join()
ok("잠금이 풀리면 성공한다", r == "stored", repr(r))
ok("재시도 사이에 backoff 로 쉬었다(1회 이상)", len(slept) >= 1, repr(slept))
ok("backoff 가 회차마다 늘어난다(0.5, 1.0…)", slept == [0.5 * (i + 1) for i in range(len(slept))], repr(slept))
n = sqlite3.connect(path).execute("SELECT COUNT(*) FROM t WHERE v='hb'").fetchone()[0]
ok("저장은 정확히 1번(재시도가 중복 저장을 만들지 않는다)", n == 1, str(n))

# 잠금 2초 · 1회만 · timeout 0.1 → DbBusy
t = threading.Thread(target=hold_lock, args=(1.0,)); t.start(); time.sleep(0.1)
try:
    db_busy.write_with_retry(path, ins, tries=1, backoff=0.01, timeout=0.1)
    got = None
except db_busy.DbBusy as e:
    got = e
except Exception as e:
    got = e
t.join()
ok("재시도를 다 쓰면 DbBusy(500 traceback 아님)", isinstance(got, db_busy.DbBusy), repr(got))

# 잠금 외 오류는 그대로
def bad(conn):
    conn.execute("INSERT INTO no_such_table VALUES(1)")
try:
    db_busy.write_with_retry(path, bad, tries=3, backoff=0.01, timeout=0.1)
    got = None
except db_busy.DbBusy as e:
    got = ("busy", e)
except sqlite3.OperationalError as e:
    got = ("op", e)
ok("잠금 외 오류(없는 표)는 삼키지 않고 그대로 올린다", got and got[0] == "op" and "no such table" in str(got[1]), repr(got))

ok("is_locked_error — 잠금 문구만 참", db_busy.is_locked_error(sqlite3.OperationalError("database is locked"))
   and not db_busy.is_locked_error(sqlite3.OperationalError("no such table: x"))
   and not db_busy.is_locked_error(ValueError("database is locked")))
ok("기본값 — 30초 대기 · 3회 · 0.5초 backoff (10초 직접 연결로 되돌리지 말 것)",
   db_busy.DEFAULT_TIMEOUT == 30.0 and db_busy.DEFAULT_TRIES == 3 and db_busy.DEFAULT_BACKOFF == 0.5)
cc = db_busy.connect_rw(path, timeout=7)
ok("connect_rw 가 PRAGMA busy_timeout 을 건다", cc.execute("PRAGMA busy_timeout").fetchone()[0] == 7000)
cc.close()

print("② 서버 배선 — collector.py")
src = read("backend/collector.py")
hb = src[src.index('@router.post("/heartbeat")'):src.index("class BlockReport")]
bl = src[src.index('@router.post("/blocked")'):src.index('@router.post("/serp")')]
ok("heartbeat 가 write_with_retry 로 저장한다", "write_with_retry(DB_PATH, lambda c: _hb_record(c, _payload))" in hb)
ok("heartbeat 가 DbBusy 를 503 으로 바꾼다", re.search(r"except DbBusy.*?status_code=503", hb, re.S) is not None)
ok("heartbeat 에 옛 직접 연결(timeout=10)이 남아 있지 않다", "sqlite3.connect(DB_PATH, timeout=10)" not in hb)
ok("blocked 가 write_with_retry 로 저장한다", "write_with_retry(DB_PATH, _ins)" in bl)
ok("blocked 가 DbBusy 를 503 으로 바꾼다", re.search(r"except DbBusy.*?status_code=503", bl, re.S) is not None)
ok("blocked 에 옛 직접 연결(timeout=10)이 남아 있지 않다", "sqlite3.connect(DB_PATH, timeout=10)" not in bl)
ok("blocked 의 INSERT 가 그대로다(칸 8개)", "INSERT INTO collector_blocks(keyword, paging_index, err, title, href, body," in bl)

print(f"\n{passed} passed · {failed} failed")
sys.exit(1 if failed else 0)
