"""회귀 — 순위 기록 순서 가드(rank_guard · 코덱스 1.22.0 `_claim_rank_projection` 이식) · 2026-09-22 3차

무엇을 막는가: 옛 전량 수집분(300위 안에 없음 = None)이 **나중에 온 양성 관측(찾음 = 37위)** 을 덮는 것.
  ① rank_guard — 더 새로운 관측이 있으면 claim False · 같은 관측은 True(멱등) · 오래된 것은 False · 봉투 없음 = 지금.
  ② record_ranks_for_keyword 실제 실행(가짜 DB · 가짜 매처·저장기) — A(전량·None) → B(양성·37) → A 재생은 건너뜀(stale=1) · B 재생은 적힘.
  ③ 구확장(봉투 없음)은 종전 그대로 항상 적힌다(무회귀).
⚠️ stdlib 만.
"""
import os
import sqlite3
import sys
import tempfile
import time
import types
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); sys.path.insert(0, BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


import rank_guard as rg

print("① rank_guard — claim / newer_targets / finished_epoch")
c = sqlite3.connect(":memory:")
T0 = 1_800_000_000
ok("첫 관측은 적힌다", rg.claim(c, "product", 1, "김치", "2026-09-22", "obs-a", T0) is True)
ok("🔴 더 오래된 관측은 못 적는다", rg.claim(c, "product", 1, "김치", "2026-09-22", "obs-old", T0 - 60) is False)
ok("🔴 같은 시각(같은 관측 재생)은 적어도 된다(멱등)", rg.claim(c, "product", 1, "김치", "2026-09-22", "obs-a", T0) is True)
ok("더 새로운 관측은 적히고 시각이 갱신된다", rg.claim(c, "product", 1, "김치", "2026-09-22", "obs-b", T0 + 600) is True
   and c.execute("SELECT finished_at, observation_id FROM collector_rank_projections WHERE target_id=1").fetchone() == (T0 + 600, "obs-b"))
ok("다른 대상·다른 축·다른 날은 서로 독립", rg.claim(c, "client", 1, "김치", "2026-09-22", "obs-old", T0 - 60) is True
   and rg.claim(c, "product", 1, "김치", "2026-09-23", "obs-old", T0 - 60) is True and rg.claim(c, "product", 2, "김치", "2026-09-22", "obs-old", T0 - 60) is True)
ok("🔴 newer_targets — 이 관측보다 새로운 것이 적힌 대상만", rg.newer_targets(c, "김치", "2026-09-22", T0) == {("product", 1)}
   and rg.newer_targets(c, "김치", "2026-09-22", T0 + 600) == set())
now = time.time()
ok("봉투 없음 → 지금(항상 최신)", abs(rg.finished_epoch(None, now) - int(now)) <= 1 and rg.observation_key(None) == "legacy")
iso = datetime(2026, 9, 22, 1, 30, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
ok("봉투 finishedAt(ISO Z) → epoch", rg.finished_epoch({"finishedAt": iso}) == int(datetime(2026, 9, 22, 1, 30, tzinfo=timezone.utc).timestamp()))
ok("finishedAt 이 깨졌으면 지금(거르지 않는 쪽)", abs(rg.finished_epoch({"finishedAt": "not-a-time"}, now) - int(now)) <= 1)
ok("observation_key 는 observationId 소문자", rg.observation_key({"observationId": "ABC-1"}) == "abc-1")
broken = types.SimpleNamespace(execute=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
ok("🔴 가드 조회가 죽으면 거르지 않는다(True)", rg.claim(broken, "product", 1, "k", "d", "o", 1) is True and rg.newer_targets(broken, "k", "d", 1) == set())
c.execute("INSERT INTO collector_rank_projections VALUES('product', 9, 'x', '2026-01-01', 'o', 1)"); c.commit()
ok("purge_old 는 오래된 날짜만 지운다", rg.purge_old(c, 30) == 1 and c.execute("SELECT COUNT(*) FROM collector_rank_projections").fetchone()[0] >= 4)

print("\n② record_ranks_for_keyword — 옛 전량 재생이 새 양성 순위를 못 덮는다(실제 실행)")
tmp = tempfile.mkdtemp(); db = os.path.join(tmp, "t.db")
os.environ["DB_PATH"] = db
conn = sqlite3.connect(db)
conn.executescript("""
CREATE TABLE tracked_products (id INTEGER PRIMARY KEY, product_url TEXT, nv_mid TEXT, disabled_at TEXT DEFAULT '');
CREATE TABLE tracked_keywords (id INTEGER PRIMARY KEY, product_id INTEGER, keyword TEXT);
INSERT INTO tracked_products VALUES (1, 'https://smartstore.naver.com/s/products/1', '111', '');
INSERT INTO tracked_keywords VALUES (10, 1, '김치');
""")
conn.commit(); conn.close()
saved = []
fake_db = types.ModuleType("database")
fake_db.save_ranking_daily = lambda **kw: saved.append(kw)
fake_db.heal_tracked_product_info = lambda *a, **k: None
fake_nc = types.ModuleType("naver_crawler")
def _find(keyword, url, prods, nv_mid=""):
    for p in prods:
        if str(p.get("productId")) == str(nv_mid):
            return p["rank"], 1, []
    return None, None, []
fake_nc.find_product_rank_from_cache = _find
sys.modules["database"] = fake_db; sys.modules["naver_crawler"] = fake_nc
sys.modules.pop("rank_record", None)
import rank_record as rr

NOW = datetime.now(timezone.utc)
def obs(oid, minutes_ago):
    return {"observationId": oid, "finishedAt": (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")}
full_a = [{"rank": i, "productId": str(900 + i)} for i in range(1, 41)]     # 목표(111) 없음 → None
partial_b = [{"rank": 37, "productId": "111"}]                              # 찾음
r1 = rr.record_ranks_for_keyword("김치", full_a, observation=obs("a", 30))
ok("A(전량 · 30분 전) → None 으로 적힌다", r1["products"] == 1 and saved[-1]["rank_position"] is None and r1.get("stale", 0) == 0)
r2 = rr.record_ranks_for_keyword("김치", partial_b, positive_only=True, observation=obs("b", 20))
ok("B(양성 · 20분 전) → 37 로 적힌다", r2["products"] == 1 and saved[-1]["rank_position"] == 37)
n_before = len(saved)
r3 = rr.record_ranks_for_keyword("김치", full_a, observation=obs("a", 30))
ok("🔴 A 를 다시 재생해도(08:00 배치처럼) 적히지 않는다 — stale 1 · 저장 호출 0", r3["products"] == 0 and r3["stale"] == 1 and len(saved) == n_before)
r4 = rr.record_ranks_for_keyword("김치", partial_b, positive_only=True, observation=obs("b", 20))
ok("같은 B 재생은 적힌다(멱등)", r4["products"] == 1 and saved[-1]["rank_position"] == 37)
r5 = rr.record_ranks_for_keyword("김치", full_a)
ok("🔴 봉투 없는 구확장 업로드는 종전 그대로 적힌다(지금 = 최신)", r5["products"] == 1 and saved[-1]["rank_position"] is None)
r6 = rr.record_ranks_for_keyword("김치", partial_b, positive_only=True, observation=obs("b", 20))
ok("그 뒤 오래된 B 는 못 덮는다", r6["products"] == 0 and r6["stale"] == 1)
gconn = sqlite3.connect(db)
row = gconn.execute("SELECT observation_id FROM collector_rank_projections WHERE axis='product' AND target_id=10").fetchone()
ok("가드 표에는 마지막으로 적힌 관측이 남는다(legacy)", row is not None and row[0] == "legacy")
gconn.close()

print(f"\n{'✅' if not failed else '❌'} 순서 가드 회귀 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
