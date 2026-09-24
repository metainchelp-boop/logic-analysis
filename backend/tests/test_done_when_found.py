"""회귀 — 추적 대상을 300위 안에서 다 찾았으면 부분 수집이어도 그날 완료 (대표 확정 2026-09-24)

대표 원문: 「키워드 별로 추적하려고 하는 상품이 몇 순위에 노출되는지 확인이 되었으면 완료로 쳐.
안 보이면 300위까지만 확인하는게 맞잖아. 1페이지든 2페이지든 300위 안에서 추적이 완료되면
완료 체크하고 다음으로 넘어가.」

왜 — 상품 추적 키워드는 확장이 「목표 다 찾으면 멈춤」(target_complete)으로 이미 끝났지만,
     업체 대표 키워드(유니버스 594개 중 591개)는 목표(nvMid)가 확장에 안 넘어가서
     1페이지에서 업체 상품을 찾아 순위를 적어 놓고도 2페이지에서 막히면 「부분」으로 남아
     같은 키워드를 계속 다시 쟀다(9/24 17시 실측 — 500회 시도 중 362회가 부분).

지키는 것
  ① 순위 기록기가 「대상 몇 개 중 몇 개를 찾았나」를 돌려준다(진짜 저장기 · 진짜 매처 · 파일 DB)
  ② 부분 수집 + 대상 전부 찾음 → 완료 표시(collector_found_done) · allTargetsFound · 수집분(collected_serp)에는 안 넣음
  ③ 부분 수집 + 하나라도 못 찾음 / 대상 0개 / 전량·목표완료 갈래 → 완료 표시 없음(종전 그대로)
  ④ 재전송(같은 observationId)은 다시 반영하지 않는다
  ⑤ 하루 완료 수(collector_daily)가 완료 표시를 함께 센다 · 부분 수에서는 뺀다
  ⑥ 배선 — /keywords 「오늘 끝낸 것」·v2 동기화에 더해진다 · v2 작업은 「완료」로 닫힌다
⚠️ stdlib + 게이트가 까는 requests·bs4 만.
"""
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

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


tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "logic_data.db")
os.environ["DB_PATH"] = DB
for _m in ("database", "rank_record", "rank_guard", "naver_crawler", "collector_observation", "collector_daily"):
    sys.modules.pop(_m, None)

import database  # noqa: E402
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
c.execute("INSERT INTO tracked_keywords(product_id, keyword) VALUES (1, '둘다키워드')")
c.execute("INSERT INTO tracked_keywords(product_id, keyword) VALUES (2, '둘다키워드')")
c.commit(); c.close()

import rank_record as rr  # noqa: E402
NOW = datetime.now(timezone.utc)
BOTH = [
    {"rank": 1, "product_id": "77777777777", "title": "x", "link": "https://smartstore.naver.com/shopb/products/2", "mall_name": "B"},
    {"rank": 2, "product_id": "88888888888", "title": "y", "link": "https://smartstore.naver.com/shopa/products/111", "mall_name": "A"},
    {"rank": 3, "product_id": "99999999999", "title": "z", "link": "https://smartstore.naver.com/shopc/products/333", "mall_name": "C"},
]
ONE = BOTH[:2]

print("① 순위 기록기가 「대상 몇 개 중 몇 개」를 돌려준다(진짜 저장기·매처)")
r = rr.record_ranks_for_keyword("둘다키워드", BOTH, positive_only=True)
ok("🔴 두 대상 다 보임 → targets_total 2 · targets_found 2", r.get("targets_total") == 2 and r.get("targets_found") == 2, str(r))
r = rr.record_ranks_for_keyword("둘다키워드", ONE, positive_only=True)
ok("🔴 하나만 보임 → 2 중 1", r.get("targets_total") == 2 and r.get("targets_found") == 1, str(r))
r = rr.record_ranks_for_keyword("대상없는키워드", BOTH, positive_only=True)
ok("대상이 없는 키워드 → 0 중 0", r.get("targets_total") == 0 and r.get("targets_found") == 0, str(r))
r = rr.record_ranks_for_keyword("둘다키워드", [], positive_only=True)
ok("상품 0건 → 0 중 0(완료로 칠 근거 없음)", r.get("targets_total") == 0 and r.get("targets_found") == 0, str(r))
ok("기존 칸(products·clients)은 그대로 온다(무회귀)", {"products", "clients"} <= set(rr.record_ranks_for_keyword("둘다키워드", BOTH).keys()))

print("\n② 부분 수집 + 대상 전부 찾음 → 그날 완료")
import collector_observation as co  # noqa: E402


def env(status, n, kw, **over):
    e = {"schemaVersion": 1, "observationId": str(uuid.uuid4()), "workerId": "w1", "keyword": kw,
         "startedAt": (NOW - timedelta(minutes=2)).isoformat(), "finishedAt": NOW.isoformat(),
         "status": status, "stopReason": "STALE_PAGE", "requestedDepth": 300,
         "pagesRead": 1, "organicCount": n, "coveredThroughRank": n, "targetIds": [],
         "pageEvidence": [{"page": 1, "keyword": kw, "source": "tap", "verified": True}]}
    e.update(over)
    return e


def payload(status, kw, n=3, **over):
    prods = [{"rank": i + 1, "productId": str(100 + i), "title": f"상품{i}", "link": f"https://smartstore.naver.com/s/products/{100 + i}"}
             for i in range(n)]
    return {"keyword": kw, "total": 500, "products": prods, "meta": {"collectorVersion": "1.27.0", "observation": env(status, n, kw, **over)}}


conn = sqlite3.connect(":memory:")
co.init_observation_db(conn)
DAY = "2026-09-24"
calls = []


def store_full(positive_only):
    calls.append(("full", positive_only)); return {"products": 1, "clients": 1, "targets_total": 2, "targets_found": 2}


def pos(total, found):
    def f():
        calls.append(("positive", None)); return {"products": found, "clients": 0, "targets_total": total, "targets_found": found}
    return f


r = co.ingest(conn, co.validate(payload("partial", "가")), DAY, store_full, pos(2, 2))
ok("🔴 부분 + 2 중 2 → allTargetsFound · projectionStatus partial_all_found", r.get("allTargetsFound") is True and r["projectionStatus"] == "partial_all_found", str(r))
ok("🔴 수집분 저장 함수(store_full)는 부르지 않는다 — 얕은 목록이 「전량」으로 쓰이지 않게", calls == [("positive", None)], str(calls))
ok("🔴 완료 표시가 남는다", co.found_done_keywords(conn, DAY) == {"가"})
ok("관측 원장은 그대로 partial·positive 로 남는다(원문 불변)",
   conn.execute("SELECT status, kind FROM collector_observations WHERE keyword='가'").fetchone() == ("partial", "positive"))

print("\n③ 완료가 아닌 경우는 종전 그대로")
calls.clear()
r = co.ingest(conn, co.validate(payload("partial", "나")), DAY, store_full, pos(2, 1))
ok("🔴 하나라도 못 찾음 → 완료 아님(300위까지 봐야 「없다」를 말한다)", r.get("allTargetsFound") is False and r["projectionStatus"] == "partial_positive" and "나" not in co.found_done_keywords(conn, DAY))
r = co.ingest(conn, co.validate(payload("partial", "다")), DAY, store_full, pos(0, 0))
ok("🔴 대상 0개 → 완료 아님(무엇을 끝냈는지 말할 수 없다)", r.get("allTargetsFound") is False and "다" not in co.found_done_keywords(conn, DAY))
r = co.ingest(conn, co.validate(payload("partial", "라")), DAY, store_full, lambda: {"products": 1, "clients": 0})
ok("옛 모양 결과(대상 수 칸 없음) → 완료 아님", r.get("allTargetsFound") is False and "라" not in co.found_done_keywords(conn, DAY))
r = co.ingest(conn, co.validate(payload("complete", "마", stopReason="DEPTH_REACHED")), DAY, store_full, pos(2, 2))
ok("전량(complete)은 종전대로 수집분 저장 갈래 · 완료 표시는 안 남긴다(수집분이 곧 완료)",
   r["projectionStatus"] == "full" and "마" not in co.found_done_keywords(conn, DAY))
r = co.ingest(conn, co.validate(payload("target_complete", "바", stopReason="TARGETS_FOUND")), DAY, store_full, pos(2, 2))
ok("목표 완료(target_complete)도 종전 갈래 그대로", r["projectionStatus"] == "full_positive" and "바" not in co.found_done_keywords(conn, DAY))
ok("all_targets_found — 이상한 값은 False", not co.all_targets_found(None) and not co.all_targets_found({"targets_total": "x"})
   and not co.all_targets_found({"targets_total": 1, "targets_found": 0}) and co.all_targets_found({"targets_total": 1, "targets_found": 1}))

print("\n④ 재전송은 다시 반영하지 않는다")
pl = payload("partial", "사")
calls.clear()
r1 = co.ingest(conn, co.validate(pl), DAY, store_full, pos(1, 1))
r2 = co.ingest(conn, co.validate(pl), DAY, store_full, pos(1, 1))
ok("🔴 같은 observationId → 한 번만 반영 · 두 번째는 duplicate · 결과는 같다",
   calls == [("positive", None)] and r2.get("duplicate") is True and r2.get("allTargetsFound") is True and r1.get("allTargetsFound") is True)
ok("완료 표시는 날짜·키워드당 한 줄", conn.execute("SELECT COUNT(*) FROM collector_found_done WHERE keyword='사'").fetchone()[0] == 1)
ok("다른 날짜 조회에는 안 섞인다", co.found_done_keywords(conn, "2026-09-25") == set())
ok("표가 없으면 빈 집합(조회 실패 = 종전 동작)", co.found_done_keywords(sqlite3.connect(":memory:"), DAY) == set())
ok("보관정책이 완료 표시도 함께 지운다(표가 있을 때)", co.purge_old(conn, days=14) >= 0)

print("\n⑤ 하루 완료 수가 완료 표시를 함께 센다")
import collector_daily as cd  # noqa: E402
conn.execute("CREATE TABLE collected_serp (keyword TEXT, collected_date TEXT)")
conn.execute("INSERT INTO collected_serp VALUES ('마', ?)", (DAY,))
conn.execute("INSERT INTO collected_serp VALUES ('가', ?)", (DAY,))   # 겹쳐도 한 번만 센다
conn.commit()
b = cd.day_block(conn, DAY, 10)
ok("🔴 완료 = 수집분 ∪ 완료 표시(겹치면 한 번) → 마·가·사 = 3", b["completed"] == 3, str(b))
ok("🔴 부분 수에서는 완료 표시된 키워드를 뺀다 → 나·다·라 = 3", b["partial"] == 3, str(b))
ok("남음 = 전체 − 완료", b["remaining"] == 7, str(b))
ok("완료 표시 표가 없으면 종전 셈(무회귀)", cd.day_block(sqlite3.connect(":memory:"), DAY, 5)["completed"] is None)

print("\n⑥ 배선(소스)")
src = read("backend/collector.py")
kw_fn = src[src.index("def _get_collect_keywords("):src.index("# ==================== 2) 수집 결과 업로드")]
i_done = kw_fn.index('"SELECT keyword FROM collected_serp WHERE collected_date = ?"')
i_found = kw_fn.index("done |= _found_done(conn, today)")
i_rem = kw_fn.index("remaining = {k: p for k, p in uni.items() if k not in done}")
ok("🔴 /keywords 의 「오늘 끝낸 것」에 완료 표시가 더해진다(남은 것 계산 전에)", i_done < i_found < i_rem)
ok("조회 실패는 종전 동작(try/except)", "except Exception as _fe" in kw_fn)
serp = src[src.index('@router.post("/serp")'):src.index("# ==================== 3) 수집 현황")]
pp = serp[serp.index("def _project_positive():"):serp.index("conn = sqlite3.connect(DB_PATH, timeout=10)\n    try:\n        try:\n            result = _obs_ingest")]
ok("🔴 부분 수집 경로는 수집분(collected_serp)에 쓰지 않는다", "INSERT INTO collected_serp" not in pp)
ok("🔴 v2 작업은 대상 다 찾으면 「완료」로 닫힌다", '_job_status = "target_complete" if result.get("allTargetsFound") else item["status"]' in serp
   and "complete_from_upload(req.meta, _job_status," in serp)
v2 = read("backend/collector_v2.py")
ok("v2 작업 원장 동기화도 완료 표시를 끝낸 것으로 본다", "done |= _found_done(conn, today)" in v2)
rr_src = read("backend/rank_record.py")
ok("🔴 기록기 — 중간에 끊기면 대상 수를 비운다(완료로 치지 않게)", "n_targets = n_found = 0   # 중간에 끊겼으면" in rr_src)

print(f"\n{passed} passed · {failed} failed")
sys.exit(1 if failed else 0)
