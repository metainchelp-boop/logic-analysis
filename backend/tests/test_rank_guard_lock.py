"""회귀 — 순서 가드가 자기 쓰기 잠금에 막히지 않는다 (2026-09-24)

무엇을 막는가
  `rank_guard.claim` 이 적은 뒤 확정하지 않고 돌아가면, 호출한 쪽이 그 연결을 쥔 채
  **다른 연결**(`database.save_ranking_daily` · `save_ranking` 은 매번 새 연결)로 순위를 저장하다
  자기 자신의 쓰기 잠금에 막힌다 — 30초 × 2회 뒤 `database is locked`, 순위는 한 줄도 안 남는다.
  9/22 가드가 들어간 뒤 운영에서 추적 상품 순위가 이틀 동안 0건이었다(rankings 마지막 9/22 10:29).

⚠️ 기존 `test_rank_guard.py` 는 저장기를 가짜로 바꿔 끼워서 **다른 연결이 실제로 쓰는 일이 없었다** —
   그래서 이 사고를 못 잡았다. 이 시험은 **진짜 `database`·진짜 `naver_crawler`** 로 파일 DB(WAL)에 쓴다.
   (게이트 환경에 requests·bs4 가 설치돼 있어 둘 다 임포트된다.)

  ① claim 이 True 를 돌려준 뒤 그 연결은 쓰기 거래를 쥐고 있지 않다 · 다른 연결이 곧바로 쓸 수 있다
  ② claim 이 False(더 새로운 관측이 있음)일 때도 거래를 남기지 않는다
  ③ record_ranks_for_keyword 실제 실행 — 봉투 있음·없음 둘 다 순위가 저장되고 몇 초 안에 끝난다
  ④ 08:00 배치 모양(같은 연결로 claim → 다른 연결로 save_ranking 을 연달아) — 두 상품 모두 저장된다
  ⑤ 순서 가드의 원래 일(오래된 관측은 못 덮는다)은 그대로다
⚠️ stdlib + 게이트가 까는 requests·bs4 만.
"""
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); sys.path.insert(0, BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "logic_data.db")
os.environ["DB_PATH"] = DB
for _m in ("database", "rank_record", "rank_guard", "naver_crawler"):
    sys.modules.pop(_m, None)

import database  # noqa: E402  — DB_PATH 를 정한 뒤에 읽어야 한다

# ⚠️ 저장기가 기다리는 시간만 줄인다(30초 → 1초). 경로·연결 방식은 그대로다 —
#    고장 난 코드로 돌리면 이 시험이 수십 초 붙잡혀 있는 대신 몇 초 안에 실패로 끝나게 하려는 것.
_orig_get_conn = database._get_conn


def _fast_conn():
    c = sqlite3.connect(database.DB_PATH, timeout=1)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=1000")
    return c


database._get_conn = _fast_conn
database.init_db()

c = sqlite3.connect(DB)
_cols = {r[1] for r in c.execute("PRAGMA table_info(tracked_products)")}
if "nv_mid" not in _cols:
    c.execute("ALTER TABLE tracked_products ADD COLUMN nv_mid TEXT DEFAULT ''")
if "disabled_at" not in _cols:
    c.execute("ALTER TABLE tracked_products ADD COLUMN disabled_at TEXT DEFAULT ''")
c.execute("INSERT INTO tracked_products(product_url, nv_mid) VALUES ('https://smartstore.naver.com/shopa/products/111', '88888888888')")
c.execute("INSERT INTO tracked_products(product_url, nv_mid) VALUES ('https://smartstore.naver.com/shopc/products/333', '99999999999')")
c.execute("INSERT INTO tracked_keywords(product_id, keyword) VALUES (1, '시험키워드')")
c.execute("INSERT INTO tracked_keywords(product_id, keyword) VALUES (2, '시험키워드')")
c.commit(); c.close()
ok("준비 — 파일 DB 가 WAL 이다(운영과 같은 잠금 방식)",
   sqlite3.connect(DB).execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal")

import rank_guard as rg  # noqa: E402


def other_can_write(timeout=0.3):
    """다른 연결이 지금 곧바로 쓸 수 있는가(기다리지 않고)."""
    o = sqlite3.connect(DB, timeout=timeout)
    try:
        o.execute("BEGIN IMMEDIATE")
        o.execute("CREATE TABLE IF NOT EXISTS _probe (x)")
        o.execute("INSERT INTO _probe VALUES (1)")
        o.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        o.close()


print("① claim 이 True 면 쓰기를 확정하고 돌아간다")
g = sqlite3.connect(DB, timeout=1)
T0 = 1_800_000_000
r = rg.claim(g, "product", 7, "k", "2026-09-24", "obs-1", T0)
ok("claim True", r is True)
ok("🔴 그 연결은 쓰기 거래를 쥐고 있지 않다", g.in_transaction is False)
ok("🔴 다른 연결이 곧바로 쓸 수 있다(0.3초 안)", other_can_write())
ok("적은 값은 다른 연결에서도 보인다(확정됨)",
   sqlite3.connect(DB).execute("SELECT finished_at FROM collector_rank_projections WHERE target_id=7").fetchone() == (T0,))

print("\n② claim 이 False 여도 거래를 남기지 않는다")
r = rg.claim(g, "product", 7, "k", "2026-09-24", "obs-old", T0 - 60)
ok("오래된 관측은 False(가드 본래 일)", r is False)
ok("거래 없음 · 다른 연결이 곧바로 쓸 수 있다", g.in_transaction is False and other_can_write())
g.close()

print("\n③ record_ranks_for_keyword 실제 실행(진짜 저장기 · 진짜 매처)")
import rank_record as rr  # noqa: E402
prods = [
    {"rank": 1, "product_id": "77777777777", "title": "x", "link": "https://smartstore.naver.com/shopb/products/2", "mall_name": "B"},
    {"rank": 2, "product_id": "88888888888", "title": "y", "link": "https://smartstore.naver.com/shopa/products/111", "mall_name": "A"},
    {"rank": 3, "product_id": "99999999999", "title": "z", "link": "https://smartstore.naver.com/shopc/products/333", "mall_name": "C"},
]
NOW = datetime.now(timezone.utc)
env = {"observationId": "00000000-0000-4000-8000-00000000000a",
       "finishedAt": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")}
t = time.time()
res = rr.record_ranks_for_keyword("시험키워드", prods, check_type="scheduled", observation=env)
dt = time.time() - t
rows = sqlite3.connect(DB).execute("SELECT product_id, rank_position FROM rankings ORDER BY product_id").fetchall()
ok("🔴 봉투 있음 — 두 상품 모두 저장된다", res.get("products") == 2 and rows == [(1, 2), (2, 3)], f"{res} {rows}")
ok("🔴 몇 초 안에 끝난다(잠금 대기 없음)", dt < 5, f"{dt:.1f}s")
ok("끝난 뒤 다른 연결이 곧바로 쓸 수 있다", other_can_write())

t = time.time()
res = rr.record_ranks_for_keyword("시험키워드", prods, check_type="scheduled", observation=None)
dt = time.time() - t
rows = sqlite3.connect(DB).execute("SELECT product_id, rank_position FROM rankings ORDER BY product_id").fetchall()
ok("봉투 없음(구확장) — 같은 날 같은 줄을 갱신한다(하루 1점)", res.get("products") == 2 and rows == [(1, 2), (2, 3)], f"{res} {rows}")
ok("봉투 없음도 몇 초 안에 끝난다", dt < 5, f"{dt:.1f}s")

print("\n④ 08:00 배치 모양 — 같은 연결로 claim, 다른 연결로 save_ranking 을 연달아")
b = sqlite3.connect(DB, timeout=1)
t = time.time()
errs = []
for pid, kid, rank in ((1, 1, 5), (2, 2, 6)):
    try:
        database.save_ranking(product_id=pid, keyword_id=kid, keyword="배치키워드", rank_position=rank,
                              page_number=1, check_type="batch-shape")
    except Exception as e:  # 고장 난 코드면 두 번째 저장이 여기서 막힌다
        errs.append(f"{type(e).__name__}: {e}")
    rg.claim(b, "product", kid, "배치키워드", "2026-09-24", "obs-batch", T0)
dt = time.time() - t
n = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM rankings WHERE check_type='batch-shape'").fetchone()[0]
ok("🔴 두 상품 모두 저장된다(두 번째가 첫 claim 의 잠금에 막히지 않는다)", n == 2 and not errs, f"n={n} {errs}")
ok("배치 모양도 몇 초 안에 끝난다", dt < 5, f"{dt:.1f}s")
b.close()

print("\n⑤ 순서 가드의 원래 일은 그대로")
old_env = {"observationId": "00000000-0000-4000-8000-00000000000b",
           "finishedAt": (NOW - timedelta(minutes=50)).isoformat().replace("+00:00", "Z")}
before = sqlite3.connect(DB).execute("SELECT product_id, rank_position FROM rankings WHERE check_type='scheduled' ORDER BY product_id").fetchall()
res = rr.record_ranks_for_keyword("시험키워드", [{"rank": 40, "product_id": "1", "link": "", "title": ""}],
                                  check_type="scheduled", observation=old_env)
after = sqlite3.connect(DB).execute("SELECT product_id, rank_position FROM rankings WHERE check_type='scheduled' ORDER BY product_id").fetchall()
ok("🔴 더 오래된 관측은 새 순위를 못 덮는다(stale 2 · 저장 0)", res.get("products") == 0 and res.get("stale") == 2 and before == after, f"{res}")

database._get_conn = _orig_get_conn
print(f"\n{'✅' if not failed else '❌'} 순서 가드 잠금 회귀 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
