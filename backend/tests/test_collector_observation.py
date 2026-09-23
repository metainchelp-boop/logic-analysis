"""회귀 — 수집 관측 원장(코덱스 1.22.0 이식판) · 2026-09-22

지키는 것:
  ① validate — 봉투 없음/어긋남 = legacy(full · 격리 없음) · complete=full · target_complete=full_positive ·
     partial=positive(상품 있을 때) · failed/paused/0건=evidence_only. 본문 기본 오류만 거절.
  ② ingest — kind 별로 store_full(positive_only)/project_positive 가 정확히 그 조합으로 불린다 ·
     같은 observationId 재전송은 저장 결과를 그대로 돌려주고 재반영하지 않는다 · 다른 본문이면 409 ·
     legacy 는 중복 차단하지 않는다(종전과 같이 덮어쓴다).
  ③ 원장 — UPDATE 는 막히고(불변) purge_old 만 지운다 · attempted_map 은 미완료(projected=0) 만 · summary.
  ④ 서버 배선 — /serp 가 validate→ingest 를 지나고 네 갈래 함수를 실제로 넘긴다 · /keywords 회전 · rank_record positive_only.
  ⑤ 매처 — 정확 식별 0순위 + 종전 폴백 유지(상세는 test_product_match_identity.py).

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없다.
"""
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta

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


import collector_observation as co

NOW = datetime.now(timezone.utc)


def env(status="complete", n=3, kw="김치", **over):
    e = {"schemaVersion": 1, "observationId": str(uuid.uuid4()), "workerId": "w1", "keyword": kw,
         "startedAt": (NOW - timedelta(minutes=2)).isoformat(), "finishedAt": NOW.isoformat(),
         "status": status, "stopReason": "DEPTH_REACHED", "requestedDepth": 300,
         "pagesRead": 1, "organicCount": n, "coveredThroughRank": n, "targetIds": [],
         "pageEvidence": [{"page": 1, "keyword": kw, "source": "tap", "verified": True}]}
    e.update(over)
    return e


def payload(status=None, n=3, kw="김치", meta_extra=None, **over):
    prods = [{"rank": i + 1, "productId": str(100 + i), "title": f"상품{i}", "link": f"https://smartstore.naver.com/s/products/{100 + i}"}
             for i in range(n)]
    meta = {"collectorVersion": "1.23.0"}
    if status is not None:
        meta["observation"] = env(status, n, kw, **over)
    if meta_extra:
        meta.update(meta_extra)
    return {"keyword": kw, "total": 500, "products": prods, "meta": meta}


print("① validate — 네 갈래 판정")
v = co.validate(payload())
ok("🔴 봉투 없음(구확장) = legacy · full · 격리 없음", v["status"] == "legacy" and v["kind"] == "full" and v["reason"] == "LEGACY")
v = co.validate(payload("complete"))
ok("🔴 complete = full", v["kind"] == "full" and v["status"] == "complete")
v = co.validate(payload("target_complete", stopReason="TARGETS_FOUND"))
ok("🔴 target_complete = full_positive(수집분 저장 + 찾은 순위만)", v["kind"] == "full_positive")
v = co.validate(payload("partial", stopReason="BLOCKED"))
ok("🔴 partial(상품 있음) = positive · 사유 실림", v["kind"] == "positive" and v["reason"] == "BLOCKED")
v = co.validate(payload("partial", n=0, stopReason="BLOCKED"))
ok("partial(0건) = evidence_only", v["kind"] == "evidence_only")
v = co.validate(payload("failed", n=0, stopReason="READ_FAILED"))
ok("failed = evidence_only", v["kind"] == "evidence_only")
v = co.validate(payload("complete", organicCount=99))
ok("🔴 봉투가 어긋나면(organicCount≠상품 수) 거절하지 않고 legacy 로 내린다 + 사유", v["kind"] == "full" and v["status"] == "legacy" and v["reason"].startswith("ENVELOPE_INVALID:organicCount"))
v = co.validate(payload("complete", kw="김치", observationId="not-a-uuid"))
ok("observationId 가 uuid 가 아니면 legacy", v["status"] == "legacy" and "observationId" in v["reason"])
v = co.validate(payload("complete", pageEvidence=[{"page": 1, "keyword": "김치", "source": "curl", "verified": True}]))
ok("증거 source 가 tap/router/nextdata 아니면 legacy", v["status"] == "legacy" and "pageEvidence" in v["reason"])
try:
    co.validate({"keyword": "", "products": []}); ok("빈 keyword 는 거절(400)", False)
except co.ObservationError as e:
    ok("빈 keyword 는 거절(400)", e.status_code == 400)
try:
    co.validate({"keyword": "a", "products": "x"}); ok("products 비목록은 거절", False)
except co.ObservationError as e:
    ok("products 비목록은 거절", e.status_code == 400)
ok("같은 본문은 같은 해시 · 다른 본문은 다른 해시", co.validate(payload())["payload_hash"] == co.validate(payload())["payload_hash"]
   and co.validate(payload())["payload_hash"] != co.validate(payload(n=2))["payload_hash"])

print("\n② ingest — 갈래별 호출과 멱등")
conn = sqlite3.connect(":memory:")
calls = []
def store_full(positive_only):
    calls.append(("full", positive_only)); return {"products": 2, "clients": 1}
def project_positive():
    calls.append(("positive", None)); return {"products": 1, "clients": 0}
r = co.ingest(conn, co.validate(payload("complete")), "2026-09-22", store_full, project_positive)
ok("🔴 complete → store_full(False) · projected", calls == [("full", False)] and r["projected"] is True and r["projectionStatus"] == "full")
calls.clear(); r = co.ingest(conn, co.validate(payload("target_complete")), "2026-09-22", store_full, project_positive)
ok("🔴 target_complete → store_full(True) · projected", calls == [("full", True)] and r["projected"] is True and r["projectionStatus"] == "full_positive")
calls.clear(); r = co.ingest(conn, co.validate(payload("partial", stopReason="STALE_PAGE")), "2026-09-22", store_full, project_positive)
ok("🔴 partial → project_positive 만 · 수집분 미저장 · projected=False", calls == [("positive", None)] and r["projected"] is False and r["projectionStatus"] == "partial_positive")
calls.clear(); r = co.ingest(conn, co.validate(payload("failed", n=0)), "2026-09-22", store_full, project_positive)
ok("failed → 아무 저장 함수도 안 부른다 · 기록만", calls == [] and r["projectionStatus"] == "evidence_only" and r["stored"] is True)
calls.clear(); r = co.ingest(conn, co.validate(payload()), "2026-09-22", store_full, project_positive)
ok("🔴 legacy(구확장) → store_full(False) 종전 그대로", calls == [("full", False)] and r["projected"] is True)
# 멱등 — 같은 observationId 같은 본문
pl = payload("complete"); oid = pl["meta"]["observation"]["observationId"]
calls.clear(); r1 = co.ingest(conn, co.validate(pl), "2026-09-22", store_full, project_positive)
r2 = co.ingest(conn, co.validate(pl), "2026-09-22", store_full, project_positive)
ok("🔴 같은 observationId 재전송은 저장 결과를 돌려주고 재반영하지 않는다", calls == [("full", False)] and r2["duplicate"] is True and r2["observationId"] == oid)
pl2 = dict(pl); pl2["products"] = pl["products"][:1]; pl2["meta"]["observation"]["organicCount"] = 1; pl2["meta"]["observation"]["coveredThroughRank"] = 1
try:
    co.ingest(conn, co.validate(pl2), "2026-09-22", store_full, project_positive); ok("같은 observationId 다른 본문 = 409", False)
except co.ObservationError as e:
    ok("같은 observationId 다른 본문 = 409", e.status_code == 409)
calls.clear(); co.ingest(conn, co.validate(payload(kw="배")), "2026-09-22", store_full, project_positive)
co.ingest(conn, co.validate(payload(kw="배")), "2026-09-22", store_full, project_positive)
ok("legacy 는 중복 차단 없이 매번 종전대로 저장한다(덮어쓰기)", calls == [("full", False), ("full", False)])

print("\n③ 원장 — 불변 · 보관정책 · attempted · summary")
n_rows = conn.execute("SELECT COUNT(*) FROM collector_observations").fetchone()[0]
try:
    conn.execute("UPDATE collector_observations SET keyword='x'"); conn.commit(); ok("🔴 원장 UPDATE 는 막힌다", False)
except sqlite3.DatabaseError as e:
    ok("🔴 원장 UPDATE 는 막힌다", "immutable" in str(e))
old_id = "legacy:oldhash"
conn.execute("INSERT INTO collector_observations(observation_id,keyword,collected_date,status,kind,payload_hash,products_json,meta_json,projected,result_json,received_at) "
             "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now','localtime','-40 day'))", (old_id, "옛", "2026-08-10", "legacy", "full", "h", "[]", "{}", 1, "{}"))
conn.commit()
ok("🔴 purge_old 는 30일 지난 행만 지운다", co.purge_old(conn) == 1 and conn.execute("SELECT COUNT(*) FROM collector_observations").fetchone()[0] == n_rows)
am = co.attempted_map(conn, "2026-09-22")
ok("🔴 attempted_map = 오늘 미완료(projected=0 · 비legacy)만 — 김치(partial·failed) 만, 배(legacy) 제외", set(am) == {"김치"})
sm = co.observation_summary(conn, "2026-09-22")
ok("summary 가 status·kind 별 건수와 최근 목록을 준다", sm["counts"] and any(c["kind"] == "positive" for c in sm["counts"]) and len(sm["latest"]) >= 3)
ok("표 없는 DB 에서 summary/attempted 는 죽지 않는다", co.attempted_map(sqlite3.connect(":memory:"), "x") == {} and co.observation_summary(sqlite3.connect(":memory:"), "x")["counts"] is None)

print("\n④ 서버 배선")
c = read("backend/collector.py")
i = c.index('@router.post("/serp")'); body = c[i:c.index("# ==================== 3) 수집 현황", i)]
ok("🔴 /serp 가 validate → ingest 를 지난다", re.search(r"item = _obs_validate\(req\.model_dump\(\)\)", body) is not None
   and re.search(r"_obs_ingest\(conn, item, today, _store_full, _project_positive\)", body) is not None)
ok("🔴 _store_full 이 positive_only 를 record_ranks_for_keyword 에 넘긴다", re.search(r"record_ranks_for_keyword\(kw, normalized, positive_only=positive_only[,)]", body) is not None)   # 3차: observation= 가산 허용
ok("🔴 _project_positive 는 수집분 INSERT 없이 positive_only=True 만", "def _project_positive" in body
   and re.search(r"def _project_positive\(\):[\s\S]{0,600}positive_only=True", body) is not None
   and "INSERT INTO collected_serp" not in body[body.index("def _project_positive"):])
ok("0건 업로드는 evidence_only 일 때만 통과(그 밖은 400 유지)", 'if not req.products and item["kind"] != "evidence_only":' in body)
ok("SerpProduct 에 nvMid·sourcePage 가 추가됐다(additive)", "nvMid: Optional[str]" in c and "sourcePage: Optional[int]" in c)
# 2026-09-23 대표 결정 B — 정렬 열쇠가 collect_order.order_key 로 옮겨 갔다(시도한 것 뒤로 → 오래 안 모은 것 먼저 → 가나다).
#    「시도한 것은 뒤로」가 여전히 **첫째 열쇠**인지 실제 함수로 확인한다(문구만 보지 않는다).
try:
    import collect_order as _co
    _ord = sorted(["가", "나", "다"], key=lambda k: _co.order_key(k, {"가": "2026-09-23T10:00"}, {"나": "2026-09-22", "다": ""}))
except Exception as _e:
    _ord = [repr(_e)]
ok("🔴 /keywords 가 시도한 키워드를 뒤로 돌린다(attempted 정렬)", "attempted = _attempted_map(conn, today)" in c
   and ("key=lambda k: (attempted.get(k, \"\"), k)" in c or "_order_key(k, attempted, last)" in c)
   and _ord == ["다", "나", "가"], str(_ord))
ok("init 에서 관측 표 보장 + 보관정책", "_obs_init(conn)" in c and "_obs_purge(conn)" in c)
ok("/status·/health 에 observations 가산", c.count('"observations": observations') == 2)
rr = read("backend/rank_record.py")
ok("🔴 rank_record.positive_only — 못 찾은 순위는 두 축 모두 건너뛴다", rr.count("if positive_only and rank is None:") == 2)
sc = read("backend/scheduler.py")
ok("01:00 보관정책 잡에 관측 원장 정리가 합류", "_obs_purge(_oc)" in sc)
nc = read("backend/naver_crawler.py")
ok("🔴 매처 — 정확 식별을 먼저 보고 종전 폴백을 남긴다", "from product_identity import canonical_product_id as _cpid" in nc and "# 2순위: productId가 URL에 포함" in nc)

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
