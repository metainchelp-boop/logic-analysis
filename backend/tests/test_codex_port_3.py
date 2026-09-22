"""회귀 — 코덱스 1.22.0 이식 3차 배선(2026-09-22)

지키는 것(소스 배선 — 게이트에 fastapi 없음):
  ① /serp 두 갈래(_store_full·_project_positive)가 봉투(observation=)를 record_ranks_for_keyword 에 넘긴다 · load_collected 가 봉투를 돌려준다 · 가드 표 보장.
  ② 08:00 배치 — 수집분 재생 전에 newer_targets 로 건너뛸 대상을 재고, 두 축 모두에서 건너뛰며, 적은 뒤 claim · API 경로에서도 이름이 정의돼 있다.
  ③ 00:30 백업 — copy2 폴백 없음 · 디스크 가드 때 선정리 없음 · closing().
  ④ tracking_eligibility day/ensure_schema · collect_watch 가 관측 원장을 본다 · nvmid 정확 식별 + ambiguous-match + 14일 창 유지.
  ⑤ 확장 v1.25.0 — rank_rules productIdentity(nvMid 우선·식별값 없는 행 제외) · net_tap 요청 범위 · 진단 파일 버튼·스크립트 · 게이트 등록.
"""
import os
import re
import sys

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


COL = read("backend/collector.py"); SCH = read("backend/scheduler.py"); RR = read("backend/rank_record.py")
TE = read("backend/tracking_eligibility.py"); CW = read("backend/collect_watch.py"); NV = read("backend/nvmid.py")
RRL = read("collector-extension/rank_rules.js"); NT = read("collector-extension/net_tap.js")
HTML = read("collector-extension/popup.html"); POP = read("collector-extension/popup.js"); MAN = read("collector-extension/manifest.json")
DEPLOY = read(".github/workflows/deploy.yml")

print("① /serp 봉투 전달 · load_collected · 가드 표")
sf = COL[COL.index("def _store_full"):COL.index("def _project_positive")]
pp = COL[COL.index("def _project_positive"):COL.index("conn = sqlite3.connect(DB_PATH, timeout=10)", COL.index("def _project_positive"))]
ok("🔴 _store_full → record_ranks_for_keyword(…, observation=item.get(\"observation\"))", re.search(r"record_ranks_for_keyword\(kw, normalized, positive_only=positive_only,\s*observation=item\.get\(\"observation\"\)\)", sf) is not None)
ok("🔴 _project_positive → positive_only=True + observation", re.search(r"record_ranks_for_keyword\(kw, normalized, positive_only=True,\s*observation=item\.get\(\"observation\"\)\)", pp) is not None)
lc = COL[COL.index("def load_collected"):COL.index("# ==================== 4) 주간 온디맨드")]
ok("🔴 load_collected 가 meta_json 의 observation 을 돌려준다(additive)", "SELECT total, products_json, meta_json FROM collected_serp" in lc and 'return {"total": r["total"] or 0, "prods": prods, "observation": observation}' in lc)
ok("load_collected — meta_json 칸 없는 옛 DB 폴백", "NULL AS meta_json" in lc and "sqlite3.OperationalError" in lc)
ok("collector init — rank_guard 표 보장 + 30일 정리", "from rank_guard import init_db as _guard_init, purge_old as _guard_purge" in COL and "_guard_init(conn)" in COL and "_guard_purge(conn)" in COL)
ok("record_ranks_for_keyword 시그니처에 observation", re.search(r"def record_ranks_for_keyword\([^)]*observation: Optional\[Dict\[str, Any\]\] = None\)", RR) is not None)
ok("🔴 양 축 모두 claim 을 지난다(product · client)", 'not _guard.claim(conn, "product", t["keyword_id"], kw, _day, _obs_key, _obs_at)' in RR and 'not _guard.claim(conn, "client", c["id"], kw, _day, _obs_key, _obs_at)' in RR)
ok("가드 모듈을 못 불러도 기록은 계속(_guard None)", re.search(r"except Exception:\s*\n\s*_guard, _obs_key, _obs_at = None, \"legacy\", 0", RR) is not None)

print("\n② 08:00 배치 순서 가드")
bt = SCH[SCH.index("def _run_rank_tracking"):SCH.index("# ==================== 08:30")]
ok("🔴 수집분 재생 전에 newer_targets 로 건너뛸 대상을 잰다", "_stale_targets = _rg.newer_targets(conn, keyword, today, _obs_at)" in bt)
ok("🔴 API 경로에서도 이름이 정의된다(_rg·_obs_at·_obs_key 초기화가 if 밖)", bt.index("_rg, _obs_at, _obs_key = None, None, None") < bt.index("if _collected:"))
ok("🔴 홈탭 축 — 건너뜀 + 적은 뒤 claim", 'if ("product", int(kw_info["id"])) in _stale_targets:' in bt and '_rg.claim(conn, "product", kw_info["id"], keyword, today, _obs_key, _obs_at)' in bt)
ok("🔴 업체 축 — 건너뜀 + 적은 뒤 claim", 'if ("client", int(cid)) in _stale_targets:' in bt and '_rg.claim(conn, "client", cid, keyword, today, _obs_key, _obs_at)' in bt)
ok("봉투 없는 수집분(구확장)은 가드 없이 종전 그대로", re.search(r"if _obs:\s*\n.*?else:\s*\n\s*_obs_at, _obs_key = None, None", bt, re.S) is not None)
ok("가드 조회 실패는 거르지 않는다", "순서 가드 조회 실패(거르지 않음)" in bt)

print("\n③ 00:30 백업 안전")
bk = SCH[SCH.index("def _run_daily_db_backup"):SCH.index("# ==================== 01:20")]
ok("🔴 .db 단독 복사 폴백 없음", re.search(r"shutil\.copy2\(\s*DB_PATH", bk) is None)
_g0 = bk.index("이번 백업 건너뜀(앱 쓰기 보호)"); _g1 = bk.index("return", _g0)
ok("🔴 디스크 가드 때 이전 세대 선정리 없음(건너뜀 문구와 return 사이에 _prune 없음)", "_prune_old_backups" not in bk[_g0:_g1] and "이전 복구 세대 보존" in bk[_g0:_g1 + 200])
ok("online backup 은 closing() 두 연결", "with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(raw_path)) as dst:" in bk)
ok("실패 시 부분 파일 삭제 + return(이전 세대 보존)", "일관 백업 실패 — 이전 백업 보존" in bk)
ok("성공 뒤 보관 정리는 그대로", bk.rfind("_prune_old_backups(backup_dir)") > bk.find("src.backup(dst)"))

print("\n④ 서버 소 조각")
ok("eligible_clients_sql(columns, *, day=None) — 날짜 검증 뒤 치환", "def eligible_clients_sql(columns: str = \"id\", *, day=None)" in TE and "date.fromisoformat(day).isoformat()" in TE)
ok("eligible_tracked_product_ids(conn, ensure_schema=True, *, day=None)", "def eligible_tracked_product_ids(conn, ensure_schema=True, *, day=None)" in TE and "eligible_clients_sql('id', day=day)" in TE)
import tracking_eligibility as te
ok("day 를 주면 SQL 의 오늘이 그 날짜로 바뀐다 · 없으면 종전", "date('2026-09-22')" in te.eligible_clients_sql(day="2026-09-22") and "date('now','localtime')" in te.eligible_clients_sql())
try:
    te.eligible_clients_sql(day="2026-13-99"); ok("깨진 날짜는 거절", False)
except ValueError:
    ok("깨진 날짜는 거절", True)
ok("collect_watch — 관측 원장 received_at 도 마지막 업로드로 본다", "MAX(received_at) m FROM collector_observations" in CW and "name='collector_observations'" in CW)
ok("nvmid — 정확 식별 우선 + 종전 폴백 + ambiguous-match", "from product_identity import naver_product_identity, canonical_product_id" in NV and '"ambiguous-match"' in NV and "naver_product_identity(link) == identity" in NV and "elif cid in link:" in NV)
ok("🔴 nvmid — 14일 창 유지(오늘만으로 좁히지 않음)", 'kws + [f"-{int(days)} day"]' in NV and "LOOKUP_DAYS = 14" in NV)
import sqlite3, json as _j
import nvmid
c = sqlite3.connect(":memory:")
c.execute("CREATE TABLE collected_serp (keyword TEXT, collected_date TEXT, products_json TEXT)")
c.execute("INSERT INTO collected_serp VALUES (?, date('now','localtime'), ?)", ("굴", _j.dumps([
    {"rank": 3, "productId": "5551", "link": "https://smartstore.naver.com/y/products/7002"},
    {"rank": 9, "productId": "5552", "link": "https://smartstore.naver.com/y/products/7002"},
    {"rank": "bad", "productId": "5553", "link": "https://smartstore.naver.com/z/products/7003"},
    {"rank": 2, "productId": "5554", "link": "https://smartstore.naver.com/q/products/7002?nvMid=1"},
])))
c.commit()
ok("🔴 같은 주소에 nvMid 둘 → ambiguous-match(자동 등록 안 함)", nvmid.lookup_from_collected(c, "https://smartstore.naver.com/y/products/7002", ["굴"])["reason"] == "ambiguous-match")
r = nvmid.lookup_from_collected(c, "https://smartstore.naver.com/z/products/7003", ["굴"])
ok("순위가 양의 정수가 아니면 순위 None 으로(값은 찾는다)", r["nv_mid"] == "5553" and r["rank"] is None)
r = nvmid.lookup_from_collected(c, "https://smartstore.naver.com/q/products/7002", ["굴"])
ok("정확 식별(스토어 다름)이 채널 번호 폴백보다 먼저 — q 스토어는 5554", r["nv_mid"] == "5554" and r["rank"] == 2)

print("\n⑤ 확장 v1.25.0")
ver = re.search(r'"version":\s*"(\d+)\.(\d+)\.(\d+)"', MAN)
ok("manifest ≥ 1.25", ver is not None and (int(ver.group(1)), int(ver.group(2))) >= (1, 25))
ok("🔴 rank_rules — productId 는 nvMid 우선 · 식별값 없는 행 제외(invalidSkipped) · productIdentity 공개", "const canonical = mid || productIdentity(p.id || p.productId);" in RRL and "st.invalidSkipped = (st.invalidSkipped || 0) + 1" in RRL and "productIdentity };" in RRL)
ok("net_tap — requestInfo/defaultScope/responseMatched 가 기록에 실린다(요청 추가 없음)", all(k in NT for k in ("function requestInfo(", "function defaultScope(", "function responseMatched(", "ent.scopeVerified = request.scopeVerified", "record(url, res.status, t, request, res.url)")))
ok("net_tap — 기본 범위 = sort rel · productSet total · pagingSize 40", "url.searchParams.get('pagingSize') === '40'" in NT)
ok("🔴 팝업 — 진단 파일 버튼·상태 줄·스크립트", 'id="diagnosticExport"' in HTML and 'id="diagnosticStatus"' in HTML and '<script src="diagnostic_export.js"></script>' in HTML and "CollectorDiagnosticExport.collect({ chromeApi: chrome })" in POP)
ok("팝업 로그 창 높이 불변(600px 상한)", re.search(r"#logs\{[^}]*height:130px", HTML) is not None)
ok("게이트 등록 — test_rank_guard · test_codex_port_3 · diagnostic_export.test.js · reader_identity.test.js",
   all(s in DEPLOY for s in ("backend/tests/test_rank_guard.py", "backend/tests/test_codex_port_3.py",
                             "collector-extension/tests/diagnostic_export.test.js", "collector-extension/tests/reader_identity.test.js")))

print(f"\n{'✅' if not failed else '❌'} 코덱스 이식 3차 배선 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
