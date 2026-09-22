"""회귀 — 코덱스 1.22.0 이식 4차(2026-09-22): 미전송 보관함 요약(telemetry) · ACK · 카탈로그 · 운영 요약(daily) · 배선

  ① collector_telemetry — 형식 검증(0 과 「못 쟀다」를 가른다) · reported_upload_summary 판정(UNREPORTED/INVALID/SESSION_CHANGED/STALE/FRESH).
  ② heartbeat — uploadSummary 저장·판정·문구 · 옛 표(칸 없음)에 ALTER 가드.
  ③ coord — 워커 표 요약 칸 · register(upload_summary=) · status 에 uploadSummary/Status.
  ④ ingest ACK — 결과에 protocol=2·payloadHash · 중복 응답에도.
  ⑤ catalog — 상품/업체 대상 · nvMid 없으면 MISSING · 연결 상품 둘 → AMBIGUOUS · 억제 제외 · 표 없으면 None.
  ⑥ daily — 완료/부분/남음 · 못 잰 값 None.
  ⑦ 배선 — v2 Register/Report uploadSummary · /daily · readiness targets.unresolved · 확장 v1.26 manifest·게이트 등록.
⚠️ stdlib 만.
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

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


print("① collector_telemetry")
import collector_telemetry as tel
NOW = 1_790_000_000
good = {"schema": 1, "count": 2, "payloadBytes": 3000, "reviewRequiredCount": 1, "oldestObservedAt": NOW - 600}
ok("정상 요약 통과(사본 반환)", tel.validate_upload_summary(good, now=NOW) == good)
bad_cases = {
    "count 0 인데 bytes>0": {**good, "count": 0, "payloadBytes": 5, "reviewRequiredCount": 0, "oldestObservedAt": None},
    "count>0 인데 bytes 0": {**good, "payloadBytes": 0},
    "검토 > 건수": {**good, "reviewRequiredCount": 3},
    "미래 관측": {**good, "oldestObservedAt": NOW + 5},
    "칸 누락": {"schema": 1, "count": 1},
    "bool": {**good, "count": True},
    "상한 초과": {**good, "count": 101},
}
for name, v in bad_cases.items():
    try:
        tel.validate_upload_summary(v, now=NOW); ok(f"거절 — {name}", False)
    except ValueError:
        ok(f"거절 — {name}", True)
ok("🔴 없음 = UNREPORTED(0 아님)", tel.reported_upload_summary(None, None, now=NOW) == (None, "UNREPORTED"))
ok("손상 = INVALID", tel.reported_upload_summary("INVALID", NOW, now=NOW)[1] == "INVALID" and tel.reported_upload_summary(json.dumps(good), "x", now=NOW)[1] == "INVALID")
ok("다른 세션 = SESSION_CHANGED", tel.reported_upload_summary(json.dumps(good), NOW, now=NOW, session_id="s2", summary_session="s1") == (None, "SESSION_CHANGED"))
s, st = tel.reported_upload_summary(json.dumps(good), NOW - 10, now=NOW)
ok("최근 = FRESH + reportedAt", st == "FRESH" and s["reportedAt"] == NOW - 10 and s["count"] == 2)
ok("5분 넘으면 STALE", tel.reported_upload_summary(json.dumps(good), NOW - 400, now=NOW)[1] == "STALE")

print("\n② heartbeat uploadSummary")
import collector_heartbeat as hb
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE collector_heartbeat (instance_id TEXT PRIMARY KEY, worker_no INTEGER DEFAULT 1, worker_count INTEGER DEFAULT 1, ext_version TEXT DEFAULT '', chrome_version TEXT DEFAULT '', reason TEXT DEFAULT '', paused_local INTEGER DEFAULT 0, paused_screen INTEGER DEFAULT 0, blocked_until TEXT DEFAULT '', slow_until TEXT DEFAULT '', running INTEGER DEFAULT 0, last_finished_at TEXT DEFAULT '', day_done INTEGER DEFAULT 0, day_total INTEGER DEFAULT 0, last_error TEXT DEFAULT '', alarms TEXT DEFAULT '', first_seen TEXT, last_seen TEXT, seen_count INTEGER DEFAULT 0)")
hb.ensure_table(conn)
cols = {r[1] for r in conn.execute("PRAGMA table_info(collector_heartbeat)")}
ok("🔴 옛 표에 upload_summary 칸을 ALTER 로 더한다(멱등)", {"upload_summary_json", "upload_summary_at"} <= cols and (hb.ensure_table(conn) is None))
now = datetime(2026, 9, 22, 12, 0, 0)
hb.record(conn, {"instanceId": "m1", "uploadSummary": {"schema": 1, "count": 3, "payloadBytes": 900, "reviewRequiredCount": 2, "oldestObservedAt": int(now.timestamp()) - 100}}, now=now)
m = hb.machines(conn, now)[0]
ok("🔴 요약 저장 + FRESH + 문구에 「📤 미전송 3건(검토 필요 2)」", m["uploadSummaryStatus"] == "FRESH" and m["uploadSummary"]["count"] == 3 and "📤 미전송 3건(검토 필요 2)" in m["status"])
hb.record(conn, {"instanceId": "m2", "uploadSummary": {"schema": 1, "count": -1}}, now=now)
m2 = [r for r in hb.machines(conn, now) if r["instance_id"] == "m2"][0]
ok("🔴 어긋난 요약은 INVALID(0 이 아니다) · 저장 단계에서도 원문을 안 받는다('INVALID' 표식)", m2["uploadSummaryStatus"] == "INVALID" and m2["uploadSummary"] is None
   and conn.execute("SELECT upload_summary_json FROM collector_heartbeat WHERE instance_id='m2'").fetchone()[0] == "INVALID")
hb.record(conn, {"instanceId": "m3"}, now=now)
m3 = [r for r in hb.machines(conn, now) if r["instance_id"] == "m3"][0]
ok("요약 없는 옛 확장(1.25 이하) = UNREPORTED · 종전 문구 그대로", m3["uploadSummaryStatus"] == "UNREPORTED" and m3["status"] == "대기(정상)")

print("\n③ coord uploadSummary")
import collector_coord as cc
c2 = sqlite3.connect(":memory:"); cc.init_db(c2)
P = cc.Policy(enabled=True)
cc.register(c2, "W1", "S1", "1.26.0", 1, 1, NOW, P, upload_summary=good)
st = cc.status(c2, NOW + 10, P)
ok("🔴 register(upload_summary=) → status.workers 에 FRESH 요약", st["workers"][0]["uploadSummaryStatus"] == "FRESH" and st["workers"][0]["uploadSummary"]["count"] == 2)
cc.register(c2, "W1", "S2", "1.26.0", 1, 1, NOW + 20, P)
ok("세션이 바뀌면 옛 요약은 SESSION_CHANGED", cc.status(c2, NOW + 30, P)["workers"][0]["uploadSummaryStatus"] == "SESSION_CHANGED")
ok("store_upload_summary — 어긋나면 INVALID", cc.store_upload_summary(c2, "W1", "S2", {"schema": 2}, NOW + 40) == "INVALID" and cc.status(c2, NOW + 41, P)["workers"][0]["uploadSummaryStatus"] == "INVALID")
ok("normalize_keyword — NFKC·공백 정리 · 빈 값 거절", cc.normalize_keyword("  김치   냉장고 ") == "김치 냉장고" and cc.normalize_keyword("ｋｉｍｃｈｉ") == "kimchi")

print("\n④ ingest ACK")
import collector_observation as co, uuid
c3 = sqlite3.connect(":memory:")
oid = str(uuid.uuid4())
pl = {"keyword": "굴", "total": 1, "products": [{"rank": 1, "productId": "1", "title": "t", "link": "https://smartstore.naver.com/s/products/1"}],
      "meta": {"observation": {"schemaVersion": 1, "observationId": oid, "workerId": "w", "keyword": "굴", "startedAt": "2026-09-22T00:00:00+00:00", "finishedAt": "2026-09-22T00:01:00+00:00",
                               "status": "complete", "stopReason": "DEPTH_REACHED", "requestedDepth": 300, "pagesRead": 1, "organicCount": 1, "coveredThroughRank": 1, "targetIds": [],
                               "pageEvidence": [{"page": 1, "keyword": "굴", "source": "tap", "verified": True}]}}}
item = co.validate(pl)
r1 = co.ingest(c3, item, "2026-09-22", lambda po: {"products": 1, "clients": 0}, lambda: {})
ok("🔴 ACK 에 protocol=2 · payloadHash · observationId", r1["protocol"] == 2 and r1["payloadHash"] == item["payload_hash"] and r1["observationId"] == oid and r1["stored"] is True)
r2 = co.ingest(c3, co.validate(pl), "2026-09-22", lambda po: {}, lambda: {})
ok("중복 응답에도 payloadHash(옛 원장 행에는 setdefault)", r2["duplicate"] is True and r2["payloadHash"] == item["payload_hash"])

print("\n⑤ catalog")
import collector_catalog as cat
c4 = sqlite3.connect(":memory:")
c4.executescript("""
CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT, status TEXT DEFAULT 'active', role TEXT DEFAULT 'advertiser', vertical TEXT DEFAULT 'store',
  auto_analysis INTEGER DEFAULT 1, track_enabled INTEGER DEFAULT 1, track_until TEXT, contract_stage TEXT, main_keywords TEXT DEFAULT '', naver_store_url TEXT);
CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT, nv_mid TEXT, disabled_at TEXT DEFAULT '', product_name TEXT);
CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INTEGER, keyword TEXT);
CREATE TABLE rank_link(client_id INTEGER, tracked_product_id INTEGER);
CREATE TABLE client_keyword_mute(client_id INTEGER, keyword TEXT);
INSERT INTO clients(id,name,main_keywords,naver_store_url,contract_stage,track_until) VALUES
 (1,'A','김치, 굴, 전복','https://smartstore.naver.com/a/products/100','진행중','2099-01-01'),
 (2,'B','새우','https://search.shopping.naver.com/catalog/555','진행중','2099-01-01'),
 (3,'C','오징어','https://smartstore.naver.com/c/products/300','계약 만료','2000-01-01');
INSERT INTO tracked_products VALUES (1,'https://smartstore.naver.com/a/products/100','777','','P1'),(2,'https://smartstore.naver.com/b/products/200','','','P2'),
 (3,'https://smartstore.naver.com/a/products/100','888','','P3'),(4,'https://smartstore.naver.com/d/products/400','999','2026-09-01','내려진 것');
INSERT INTO tracked_keywords VALUES (10,1,'김치'),(11,2,'전복'),(12,4,'가리비');
INSERT INTO rank_link VALUES (1,1);
INSERT INTO client_keyword_mute VALUES (1,'전복');
""")
rows = cat.catalog_sources(c4)
byk = {(r["source"], r["sourceKeyword"]): r for r in rows}
ok("🔴 상품 — 등록 nvMid 있으면 targetId · 없으면 MISSING_PRODUCT_ID", byk[("product", "김치")]["targetId"] == "777" and byk[("product", "전복")]["issue"] == "MISSING_PRODUCT_ID")
ok("🔴 내려진 상품(disabled_at)은 대상이 아니다", ("product", "가리비") not in byk)
ok("🔴 업체 — 연결 상품의 정확 주소로 nvMid · 억제 키워드(전복)는 빠진다 · 카탈로그 주소는 그 nvMid", byk[("client", "김치")]["targetId"] == "777" and ("client", "전복") not in byk and byk[("client", "새우")]["targetId"] == "555")
c4.execute("INSERT INTO rank_link VALUES (1,3)")
rows = cat.catalog_sources(c4); byk = {(r["source"], r["sourceKeyword"]): r for r in rows}
ok("🔴 같은 정확 주소에 연결 상품 nvMid 둘 → AMBIGUOUS_PRODUCT_ID", byk[("client", "김치")]["issue"] == "AMBIGUOUS_PRODUCT_ID")
ok("자격 없는 업체(계약 만료)는 대상이 아니다", ("client", "오징어") not in byk)
ok("unresolved_count 는 issue 있는 것만", cat.unresolved_count(c4) == sum(1 for r in rows if r["issue"]))
ok("🔴 표가 없으면 None(0 이 아니다)", cat.catalog_sources(sqlite3.connect(":memory:")) is None and cat.unresolved_count(sqlite3.connect(":memory:")) is None)

print("\n⑥ daily")
import collector_daily as cd
c5 = sqlite3.connect(":memory:")
c5.executescript("CREATE TABLE collected_serp(keyword TEXT, collected_date TEXT); INSERT INTO collected_serp VALUES ('a','2026-09-22'),('b','2026-09-22'),('c','2026-09-21');")
d = cd.summary(c5, "2026-09-22", 10, 1, [], {"state": "READY"}, 4, False, 1)
ok("🔴 오늘 완료 2 · 남음 8 · 부분 None(원장 없음) · 어제 완료 1 · 미해결 1 · 대기 요청 4", d["today"]["completed"] == 2 and d["today"]["remaining"] == 8 and d["today"]["partial"] is None and d["yesterday"]["completed"] == 1 and d["today"]["unresolved"] == 1 and d["pendingRequests"] == 4 and d["yesterdayDay"] == "2026-09-21")
c5.executescript("CREATE TABLE collector_observations(keyword TEXT, collected_date TEXT, kind TEXT); INSERT INTO collector_observations VALUES ('z','2026-09-22','positive'),('z','2026-09-22','positive'),('y','2026-09-22','full');")
d = cd.summary(c5, "2026-09-22", None, None, None, None, None, True, 1)
ok("부분 수집은 키워드 기준으로 1 · 유니버스 모르면 total/remaining None", d["today"]["partial"] == 1 and d["today"]["total"] is None and d["today"]["remaining"] is None and d["machines"] is None)
ok("🔴 표가 없으면 completed None(0 아님)", cd.day_block(sqlite3.connect(":memory:"), "2026-09-22", 5)["completed"] is None)

print("\n⑦ 배선")
V2 = read("backend/collector_v2.py"); COL = read("backend/collector.py"); MAN = read("collector-extension/manifest.json"); DEPLOY = read(".github/workflows/deploy.yml")
ok("v2 Register/Report 에 uploadSummary", V2.count("uploadSummary: Optional[dict] = None") == 2 and "upload_summary=req.uploadSummary" in V2 and "core.store_upload_summary(conn, req.workerId, req.sessionId, req.uploadSummary, now)" in V2)
ok("🔴 GET /daily 는 로그인 경로 · collector_daily.summary 사용", '@router.get("/daily")' in V2 and "Depends(get_current_user)" in V2[V2.index('@router.get("/daily")'):V2.index('@router.get("/daily")') + 400] and "from collector_daily import summary as _daily" in V2)
ok("readiness 가 targets.unresolved 를 싣고 있으면 blocker", 'out["targets"] = {"unresolved": unresolved_count(conn, out.get("day"))}' in V2 and "TARGET_IDENTITIES_UNRESOLVED" in V2)
ok("HeartbeatReport.uploadSummary", "uploadSummary: Optional[dict] = None" in COL)
ver = re.search(r'"version":\s*"(\d+)\.(\d+)\.(\d+)"', MAN)
ok("manifest ≥ 1.26", ver is not None and (int(ver.group(1)), int(ver.group(2))) >= (1, 26))
ok("게이트 등록 — test_codex_port_4 · outbox.test.js", "backend/tests/test_codex_port_4.py" in DEPLOY and "collector-extension/tests/outbox.test.js" in DEPLOY)

print(f"\n{'✅' if not failed else '❌'} 코덱스 이식 4차 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
