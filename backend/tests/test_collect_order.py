"""회귀 — 수집 순서: 같은 시간대 안에서 **오래 안 모은 키워드부터** (대표 결정 B · 2026-09-23)

지키는 것:
  ① order_key — 오늘 시도한 것은 뒤로(종전) → 한 번도 안 모은 것 → 오래전에 모은 것 → 가나다(종전).
  ② last_collected_map — 키워드별 마지막 수집일 · 표가 없거나 깨져도 예외 없이 빈 dict(= 종전 가나다순).
  ③ /keywords 배선 — 시간대 슬롯·밀린 것 두 정렬이 모두 같은 열쇠를 쓰고, 전량 모드도 같다 ·
     슬롯·시간당 상한·시험 상한·기계 나누기는 그대로다(소스 확인 — fastapi 없는 게이트라 import 불가).
  ④ 중앙 배정 v2(claim) — 실제 DB 로: 같은 슬롯·같은 시도 횟수면 **오래 안 모은 것**을 먼저 임대한다.
  ⑤ 🔴 모의 실험 — 같은 수집량(하루 요청 수 동일)에서, 분석이 쓰는 「오늘·어제」 창에 들어오는 키워드가
     가나다순보다 늘어나고 · 며칠 안에 **모든 키워드가 한 번씩** 모인다. 가나다순은 영영 못 모으는 키워드가 남는다.
"""
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

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


import collect_order as co  # noqa: E402
import collect_slot  # noqa: E402

print("① order_key")
att = {"다": "2026-09-23T09:00:00"}
last = {"가": "2026-09-22", "나": "2026-09-10", "라": "2026-09-22"}
got = sorted(["가", "나", "다", "라", "마"], key=lambda k: co.order_key(k, att, last))
ok("🔴 한 번도 안 모은 것(마) → 오래전(나) → 최근(가·라 가나다) → 오늘 시도한 것(다)", got == ["마", "나", "가", "라", "다"], str(got))
ok("열쇠가 없으면(빈 dict) 종전 가나다순과 같다",
   sorted(["다", "가", "나"], key=lambda k: co.order_key(k, {}, {})) == ["가", "나", "다"])
ok("None 도 받는다(방어)", co.order_key("가", None, None) == ("", "", "가"))

print("\n② last_collected_map")
conn = sqlite3.connect(":memory:")
ok("표가 없으면 예외 없이 빈 dict", co.last_collected_map(conn) == {})
conn.executescript("""
    CREATE TABLE collected_serp (id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL,
        collected_date TEXT NOT NULL, total INTEGER DEFAULT 0, products_json TEXT NOT NULL);
    CREATE UNIQUE INDEX idx_collected_serp_uniq ON collected_serp(keyword, collected_date);
""")
for kw, d in [("가", "2026-09-20"), ("가", "2026-09-22"), ("나", "2026-09-15")]:
    conn.execute("INSERT INTO collected_serp(keyword, collected_date, products_json) VALUES (?,?,'[]')", (kw, d))
m = co.last_collected_map(conn)
ok("🔴 키워드별 가장 최근 수집일", m == {"가": "2026-09-22", "나": "2026-09-15"}, str(m))
plan = " ".join(r[3] for r in conn.execute(
    "EXPLAIN QUERY PLAN SELECT keyword, MAX(collected_date) FROM collected_serp GROUP BY keyword"))
ok("유일 색인(keyword, collected_date)으로 덮인다 — 표 본문(products_json)을 안 읽는다",
   "COVERING INDEX" in plan and "idx_collected_serp_uniq" in plan, plan)

print("\n③ /keywords 배선(소스)")
src = open(os.path.join(BACKEND, "collector.py"), encoding="utf-8").read()
i = src.index('@router.get("/keywords")')
body = src[i:src.index("# ==================== 2) 수집 결과 업로드", i)]
ok("🔴 마지막 수집일을 읽는다(collect_order.last_collected_map)", "from collect_order import last_collected_map" in body and "last = _last_map(conn)" in body)
ok("🔴 이번 시간대 슬롯 정렬이 같은 열쇠", "now_slot.sort(key=lambda k: _order_key(k, attempted, last))" in body)
ok("🔴 밀린 슬롯 정렬도 같은 열쇠(시도·마지막 수집일) 다음에 오래 밀린 슬롯",
   "overdue.sort(key=lambda pair: (_order_key(pair[1], attempted, last)[:2], pair[0], pair[1]))" in body)
ok("🔴 전량 모드(구확장)도 같은 열쇠", "sorted(remaining, key=lambda k: _order_key(k, attempted, last))[:MAX_KEYWORDS]" in body)
ok("불러오기 실패면 종전(시도 → 가나다)으로 폴백", "except Exception:\n            last = {}" in body and "_order_key = lambda" in body)
ok("시간당 상한·시험 상한·기계 나누기·슬롯은 그대로",
   "picked = now_slot[:HOURLY_CAP]" in body and "picked = _apply_cap(picked, cap)" in body
   and "_split_ok(k, w, wc)" in body and "s = _slot_of(k, p)" in body)

print("\n④ 중앙 배정 v2 claim — 실제 DB")
import collector_coord as cc  # noqa: E402
P = cc.Policy(enabled=True, global_hourly=40, global_daily=1200, worker_hourly=40, worker_daily=240, min_gap_seconds=1,
              lease_seconds=600, session_seconds=900, requested_depth=300, transient_retries=1, retry_backoff_seconds=60)
NOW = int(datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).timestamp())
DAY = cc.business_day(NOW)
c4 = sqlite3.connect(":memory:"); cc.init_db(c4)
c4.executescript("""
    CREATE TABLE collected_serp (id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL,
        collected_date TEXT NOT NULL, total INTEGER DEFAULT 0, products_json TEXT NOT NULL);
""")
for kw, d in [("가", "2026-09-22"), ("나", "2026-09-12")]:     # 다 = 한 번도 없음
    c4.execute("INSERT INTO collected_serp(keyword, collected_date, products_json) VALUES (?,?,'[]')", (kw, d))
c4.commit()
cc.sync_daily(c4, DAY, {"가": True, "나": True, "다": True}, {}, lambda k, p: 10)
cc.register(c4, "W", "S", "1.26.0", 1, 1, NOW, P)
order = []
for t in range(3):
    r = cc.claim(c4, "W", "S", NOW + t * 60, P, 10, lambda kw, w, wc: True)
    if r.get("job"):
        order.append(r["job"]["keyword"])
        c4.execute("UPDATE collector_coord_jobs SET state='done' WHERE keyword=?", (r["job"]["keyword"],)); c4.commit()
ok("🔴 같은 슬롯·같은 시도 횟수면 한 번도 없음(다) → 오래전(나) → 최근(가)", order == ["다", "나", "가"], str(order))
c5 = sqlite3.connect(":memory:"); cc.init_db(c5)   # collected_serp 표가 없는 DB — 예외 없이 종전 가나다순
cc.sync_daily(c5, DAY, {"나": True, "가": True}, {}, lambda k, p: 10)
cc.register(c5, "W", "S", "1.26.0", 1, 1, NOW, P)
r = cc.claim(c5, "W", "S", NOW, P, 10, lambda kw, w, wc: True)
ok("수집분 표가 없어도 임대는 된다(종전 가나다순)", r["state"] == "LEASED" and r["job"]["keyword"] == "가", str(r.get("job")))

print("\n⑤ 🔴 모의 실험 — 같은 수집량에서 분석 창(오늘·어제)에 들어오는 키워드")


def simulate(rotate: bool, n_kw=594, per_hour=12, days=10):
    """실제 슬롯 규칙(collect_slot.slot_of)으로 하루 24시간을 돌린다. 시간당 per_hour 개만 담는다.
    ⚠️ 실측 기준(9/19~9/23 하루 174~387개)에 맞춰 시간당 12개 ≈ 하루 288개로 둔다.
    분석은 08:30 에 「오늘·어제」 수집분만 쓴다(serve_from_collected) — 그 창에 든 키워드 수를 센다."""
    kws = [f"키워드{i:03d}" for i in range(n_kw)]
    prio = {k: (i % 3 != 0) for i, k in enumerate(kws)}       # 대표 키워드 약 2/3 · 추적 전용 약 1/3
    lastd = {}
    d0 = date(2026, 9, 24)
    window_hits, per_day_requests, ever = [], [], set()
    for day in range(days):
        today = (d0 + timedelta(days=day)).isoformat()
        yday = (d0 + timedelta(days=day - 1)).isoformat()
        done = set()
        reqs = 0
        for h in range(24):
            if h == 8:   # 08:30 자동 분석 시점 — 오늘·어제 수집분이 있는 키워드 수
                window_hits.append(sum(1 for k in kws if lastd.get(k) in (today, yday)))
            remaining = [k for k in kws if k not in done]
            key = (lambda k: co.order_key(k, {}, lastd)) if rotate else (lambda k: ("", "", k))
            now_slot = sorted([k for k in remaining if collect_slot.slot_of(k, prio[k]) == h], key=key)
            overdue = sorted([(collect_slot.slot_of(k, prio[k]), k) for k in remaining
                              if collect_slot.slot_of(k, prio[k]) < h],
                             key=lambda pr: (key(pr[1])[:2], pr[0], pr[1]))
            picked = now_slot[:per_hour]
            if len(picked) < per_hour:
                picked += [k for _s, k in overdue[:per_hour - len(picked)]]
            for k in picked:
                done.add(k); lastd[k] = today; ever.add(k)
            reqs += len(picked)
        per_day_requests.append(reqs)
    return window_hits, per_day_requests, len(ever)


alpha_hits, alpha_reqs, alpha_ever = simulate(rotate=False)
rot_hits, rot_reqs, rot_ever = simulate(rotate=True)
print(f"    가나다순 — 08:30 창 {alpha_hits[2:]} · 하루 요청 {alpha_reqs[2:5]} · 10일간 한 번이라도 모인 것 {alpha_ever}/594")
print(f"    오래된 것 먼저 — 08:30 창 {rot_hits[2:]} · 하루 요청 {rot_reqs[2:5]} · 10일간 한 번이라도 모인 것 {rot_ever}/594")
ok("🔴 하루 요청 수(= 네이버에 가는 양)는 똑같다", alpha_reqs == rot_reqs, f"{alpha_reqs} vs {rot_reqs}")
ok("🔴 분석 창(오늘·어제)에 들어오는 키워드가 가나다순보다 많다(3일째부터 매일)",
   all(r > a for r, a in zip(rot_hits[2:], alpha_hits[2:])), f"{rot_hits} vs {alpha_hits}")
ok("🔴 며칠 안에 모든 키워드가 한 번씩 모인다(가나다순은 영영 못 모으는 키워드가 남는다)",
   rot_ever == 594 and alpha_ever < 594, f"회전 {rot_ever} · 가나다 {alpha_ever}")

print(f"\n결과: {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
