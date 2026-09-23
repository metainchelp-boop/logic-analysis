"""nvMid 필수·자동 찾기·조기 종료 목표 — 회귀 시험 (2026-09-18 대표 확정)

무엇을 지키나
  ① **새 등록은 nvMid 없이 통과하면 안 된다** — 서버가 최종 방어선이다(업체 칸과 같은 자리).
  ② **기존 443개는 막지 않는다**(대표 확정 A안) — 소급해 막으면 오늘부터 순위가 안 쌓인다.
  ③ **자동 찾기는 네이버에 요청하지 않는다** — 이미 모은 수집분에서만 본다.
  ④ **못 찾은 이유를 구분해 돌려준다** — 「없다」와 「지금 안 된다」를 섞으면 직원이 할 일을 못 고른다.
  ⑤ **조기 종료 목표는 nvMid 가 있는 상품만** 넣는다 — 없는 것을 목표로 두면 영원히 못 찾아
     조기 종료가 통째로 죽는다.

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi 가 없다 — collect_cap·split_rule 과 같은 이유).
⚠️ 그래서 ①②는 소스 검사로, ③④⑤는 **가짜 DB 로 실제 실행**해서 본다.
"""
import io
import os
import re
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
CRAWL = io.open(os.path.join(ROOT, "naver_crawler.py"), encoding="utf-8").read()
COLL = io.open(os.path.join(ROOT, "collector.py"), encoding="utf-8").read()
EXT = io.open(os.path.join(ROOT, "..", "collector-extension", "background.js"),
              encoding="utf-8").read()

import nvmid  # noqa: E402

_p = _f = 0


def ok(name, cond):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS  {name}")
    else:
        _f += 1
        print(f"  FAIL  {name}")


def code(src):
    """주석을 떼고 본다 — 주석에 옛 코드를 적어 두는 관행 때문에 헛실패한 적이 있다."""
    return re.sub(r"#[^\n]*", "", src)


# ── ① 새 등록은 nvMid 없이 통과하면 안 된다 ──────────────────────────────
print("\n[① 새 등록 — nvMid 없으면 400]")
i = MAIN.find("def track_product(")
TRACK = code(MAIN[i:MAIN.find("\n@app.", i + 10)] if MAIN.find("\n@app.", i + 10) > 0 else MAIN[i:])
ok("① 등록 경로가 있다", i > 0)
ok("① nvMid 를 검사한다", "nv_mid" in TRACK)
# ⚠️ **문구가 아니라 조건으로 본다.** 사보타주 검증에서 `if not _nv:` 를 `if False:` 로
#    바꿨더니 문구는 전부 남아 있어 시험이 통과했다 — 이 저장소가 두 번째로 겪는 함정이다
#    (확장 쪽 `if (false)` 와 같은 모양). 조건식 자체를 못박는다.
ok("🔴① 빈 값 가드가 **조건으로** 살아 있다(`if not _nv:`)",
   re.search(r"if\s+not\s+_nv\s*:", TRACK) is not None)
ok("🔴① 모양 가드도 **조건으로** 살아 있다(`if not _nv_ok(_nv):`)",
   re.search(r"if\s+not\s+_nv_ok\(\s*_nv\s*\)\s*:", TRACK) is not None)
ok("🔴① 가드가 상수로 무력화돼 있지 않다(if False/if 0)",
   re.search(r"if\s+(False|0)\s*:", TRACK) is None)
ok("① 두 가드 모두 400 으로 막는다", TRACK.count("status_code=400") >= 3)
ok("① 정규화를 거친 값으로 판정한다(원문이 아니라)",
   re.search(r"_nv\s*=\s*_nv_norm\(\s*req\.nv_mid\s*\)", TRACK) is not None)
ok("① 업체 필수 차단은 그대로 남아 있다(무회귀)", "업체를 선택해야 등록됩니다" in TRACK)
# ⚠️ 문구가 아니라 **순서**로 본다 — 업체 검사보다 뒤여야 기존 안내가 안 가려진다.
ok("① 업체 검사 **뒤**에 온다(기존 안내를 안 가린다)",
   TRACK.index("업체를 선택해야 등록됩니다") < TRACK.index("nvMid"))
ok("① 저장까지 이어진다", "nv_mid=_nv" in TRACK)

# ── ② 기존 443개는 막지 않는다 (A안) ─────────────────────────────────────
print("\n[② 기존 것은 계속 추적한다 — 대표 확정 A안]")
DB = code(io.open(os.path.join(ROOT, "database.py"), encoding="utf-8").read())
ok("② add_tracked_product 의 nv_mid 는 **선택 인자**다(다른 호출처 무회귀)",
   "nv_mid: str = None" in DB)
ok("② 빈 값이 기존 nv_mid 를 지우지 않는다(COALESCE+NULLIF)",
   "COALESCE(NULLIF(?, ''), nv_mid)" in DB)
FRC = code(CRAWL[CRAWL.find("def find_product_rank_from_cache("):])
FRC = FRC[:FRC.find("\ndef ")] if FRC.find("\ndef ") > 0 else FRC
ok("② 매칭의 nv_mid 도 **선택 인자**다(안 넘기면 종전 규칙)",
   'nv_mid: str = ""' in FRC)
ok("② nvMid 가 있으면 그걸 먼저 본다",
   FRC.index("target_nv_mid") < FRC.index("target_product_id ==")
   if "target_product_id ==" in FRC else False)
ok("② 종전 2·3순위 규칙이 그대로 남아 있다",
   "target_product_id in product[\"product_url\"]" in FRC and "target_store_name" in FRC)

# ── ③④ 자동 찾기 — 실제로 돌려 본다 ────────────────────────────────────
print("\n[③④ 자동 찾기 — 수집분에서만 · 못 찾은 이유를 가른다]")
LOOKUP = code(MAIN[MAIN.find("def nvmid_lookup("):][:2500])
ok("③ 자동 찾기 경로가 있다", "/api/products/nvmid-lookup" in MAIN)
ok("🔴③ **네이버를 부르지 않는다**(수집분 조회만)",
   "lookup_from_collected" in LOOKUP
   and "requests." not in LOOKUP and "search_products" not in LOOKUP)

with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "t.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE collected_serp (keyword TEXT, collected_date TEXT, products_json TEXT)")
    c.execute("CREATE TABLE tracked_products (id INTEGER PRIMARY KEY, nv_mid TEXT)")
    c.execute("CREATE TABLE tracked_keywords (id INTEGER PRIMARY KEY, product_id INT, keyword TEXT)")
    import json as _j
    c.execute("INSERT INTO collected_serp VALUES (?, date('now','localtime'), ?)",
              ("갈치조림", _j.dumps([
                  {"rank": 1, "productId": "99990001",
                   "link": "https://smartstore.naver.com/x/products/7001"},
                  {"rank": 12, "productId": "88880002",
                   "link": "https://smartstore.naver.com/y/products/7002"},
              ])))
    c.commit()

    got = nvmid.lookup_from_collected(c, "https://smartstore.naver.com/y/products/7002", ["갈치조림"])
    ok("③ 주소로 nvMid 를 되찾는다", got["nv_mid"] == "88880002")
    ok("③ 어느 키워드 몇 위에서 봤는지도 돌려준다",
       got["keyword"] == "갈치조림" and got["rank"] == 12)

    # ④ 못 찾은 이유 셋이 서로 구분되는가 — 직원이 할 일이 셋 다 다르다
    r1 = nvmid.lookup_from_collected(c, "https://example.com/no-id-here", ["갈치조림"])
    ok("④ 주소에서 번호를 못 뽑으면 no-channel-id", r1["reason"] == "no-channel-id")
    r2 = nvmid.lookup_from_collected(c, "https://smartstore.naver.com/y/products/7002", ["안모은키워드"])
    ok("④ 안 모은 키워드면 not-collected", r2["reason"] == "not-collected")
    r3 = nvmid.lookup_from_collected(c, "https://smartstore.naver.com/z/products/9999", ["갈치조림"])
    ok("④ 모았는데 없으면 not-in-serp(진짜 순위 밖일 수 있다)", r3["reason"] == "not-in-serp")
    ok("🔴④ 셋이 서로 다른 값이다(한 덩어리로 뭉치면 안내를 못 고른다)",
       len({r1["reason"], r2["reason"], r3["reason"]}) == 3)

    # ⑤ 조기 종료 목표
    print("\n[⑤ 조기 종료 목표 — nvMid 있는 것만]")
    c.execute("INSERT INTO tracked_products VALUES (1, '88880002')")
    c.execute("INSERT INTO tracked_products VALUES (2, '')")        # 아직 안 채운 것(A안)
    c.execute("INSERT INTO tracked_products VALUES (3, '77770003')")
    c.execute("INSERT INTO tracked_keywords VALUES (1, 1, '갈치조림')")
    c.execute("INSERT INTO tracked_keywords VALUES (2, 2, '갈치조림')")   # 빈 nv_mid
    c.execute("INSERT INTO tracked_keywords VALUES (3, 2, '감귤')")       # 빈 것만 있는 키워드
    c.execute("INSERT INTO tracked_keywords VALUES (4, 3, '갈치조림')")
    c.commit()
    t = nvmid.targets_for_keywords(c, ["갈치조림", "감귤", "없는키워드"])
    ok("⑤ nvMid 가 있는 것만 목표가 된다",
       sorted(t.get("갈치조림", [])) == ["77770003", "88880002"])
    ok("🔴⑤ **빈 nvMid 만 있는 키워드는 키를 아예 안 만든다**(0개 목표 = 즉시 종료 오해 방지)",
       "감귤" not in t)
    ok("🔴⑤ 목표가 없는 키워드도 키를 안 만든다", "없는키워드" not in t)
    ok("⑤ 빈 목록을 넣으면 빈 결과", nvmid.targets_for_keywords(c, []) == {})
    c.close()

# ── 모양 검사 ─────────────────────────────────────────────────────────────
print("\n[모양 — 사람이 붙여넣는 실수를 여기서 잡는다]")
ok("normalize — 주소를 붙여넣어도 nvMid 만 뽑는다",
   nvmid.normalize("https://search.shopping.naver.com/catalog/x?nvMid=12345678&a=1") == "12345678")
ok("normalize — 쉼표·공백을 지운다", nvmid.normalize(" 12,345,678 ") == "12345678")
ok("normalize — 빈 값은 빈 문자열", nvmid.normalize(None) == "" and nvmid.normalize("  ") == "")
ok("is_valid — 8자리는 통과", nvmid.is_valid("12345678"))
ok("is_valid — 7자리는 거절(오타 방어)", not nvmid.is_valid("1234567"))
ok("is_valid — 21자리는 거절(주소 통째 붙여넣기 방어)", not nvmid.is_valid("1" * 21))
ok("is_valid — 글자만 있으면 거절", not nvmid.is_valid("abcdefgh"))
ok("channel_id_from_url — 스마트스토어", nvmid.channel_id_from_url(
    "https://smartstore.naver.com/shop/products/7654321") == "7654321")
ok("channel_id_from_url — 카탈로그", nvmid.channel_id_from_url(
    "https://search.shopping.naver.com/catalog/9876543") == "9876543")
ok("channel_id_from_url — nvMid 주소가 먼저다", nvmid.channel_id_from_url(
    "https://x/catalog/111?nvMid=222") == "222")

# ── ⑥ 일괄 채우기 + 「없으면 추적 안 함」 스위치 (2026-09-18 대표 지시) ──────
print("\n[⑥ 일괄 채우기 — 서버가 444개를 스스로 메운다]")
with tempfile.TemporaryDirectory() as d2:
    import json as _j2
    c2 = sqlite3.connect(os.path.join(d2, "b.db"))
    c2.execute("CREATE TABLE collected_serp (keyword TEXT, collected_date TEXT, products_json TEXT)")
    c2.execute("CREATE TABLE tracked_products (id INTEGER PRIMARY KEY, product_url TEXT, nv_mid TEXT)")
    c2.execute("CREATE TABLE tracked_keywords (id INTEGER PRIMARY KEY, product_id INT, keyword TEXT)")
    c2.execute("INSERT INTO collected_serp VALUES (?, date('now','localtime'), ?)",
               ("갈치조림", _j2.dumps([
                   {"rank": 3, "productId": "70000000001",
                    "link": "https://smartstore.naver.com/a/products/5001"},
               ])))
    # 1 = 찾아짐 · 2 = 이미 채워짐(덮으면 안 됨) · 3 = 수집분에 없음
    c2.execute("INSERT INTO tracked_products VALUES (1, 'https://smartstore.naver.com/a/products/5001', '')")
    c2.execute("INSERT INTO tracked_products VALUES (2, 'https://smartstore.naver.com/a/products/5001', '99999999999')")
    c2.execute("INSERT INTO tracked_products VALUES (3, 'https://smartstore.naver.com/b/products/6002', '')")
    for i2, pid2 in ((1, 1), (2, 2), (3, 3)):
        c2.execute("INSERT INTO tracked_keywords VALUES (?, ?, '갈치조림')", (i2, pid2))
    c2.commit()

    got2 = nvmid.backfill_from_collected(c2)
    ok("⑥ 빈 것만 검사한다(이미 채워진 것은 안 본다)", got2["scanned"] == 2)
    ok("⑥ 수집분에서 찾아 채운다", got2["filled"] == 1)
    ok("⑥ 채운 값이 실제로 저장된다",
       c2.execute("SELECT nv_mid FROM tracked_products WHERE id=1").fetchone()[0] == "70000000001")
    ok("🔴⑥ **이미 채워진 값은 절대 안 덮는다**(사람이 넣은 값이 우선)",
       c2.execute("SELECT nv_mid FROM tracked_products WHERE id=2").fetchone()[0] == "99999999999")
    ok("⑥ 못 찾은 것은 비운 채 둔다(가짜 값을 넣지 않는다)",
       (c2.execute("SELECT nv_mid FROM tracked_products WHERE id=3").fetchone()[0] or "") == "")
    ok("⑥ 못 찾은 사유를 센다", got2["by_reason"].get("not-in-serp", 0) >= 1)
    ok("⑥ 남은 명단을 낼 수 있다(직원이 처리할 목록)",
       [r["id"] for r in nvmid.missing_rows(c2)] == [3])
    ok("⑥ 두 번 돌려도 더 안 채운다(멱등)",
       nvmid.backfill_from_collected(c2)["filled"] == 0)
    c2.close()

print("\n[⑥ 「nvMid 없으면 추적 안 함」 스위치 — 기본은 꺼짐]")
TE = code(io.open(os.path.join(ROOT, "tracking_eligibility.py"), encoding="utf-8").read())
ok("🔴⑥ **기본값이 꺼짐이다**(지금 444개가 전부 비어 있어 켜면 기록이 0 이 된다)",
   re.search(r"NVMID_REQUIRED_DEFAULT\s*=\s*False", TE) is not None)
ok("⑥ env 로도 켤 수 있다(서버에서 즉시 되돌리는 문)", "NVMID_REQUIRED" in TE)
RR = code(io.open(os.path.join(ROOT, "rank_record.py"), encoding="utf-8").read())
ok("⑥ 기록 경로가 그 스위치를 본다", "nvmid_required" in RR)
ok("🔴⑥ 판정이 깨지면 **거르지 않는다**(기록이 멈추는 쪽이 더 나쁘다)",
   "거르지 않음" in RR or "거르지 않는다" in RR)
ok("⑥ 켜져 있을 때만 거른다(조건으로)",
   re.search(r"if\s+nvmid_required\(\)\s*:", RR) is not None)

print("\n[⑥ 상한 — 대표 지시 15(2026-09-23 · 종전 10)]")
CAP = code(io.open(os.path.join(ROOT, "collect_cap.py"), encoding="utf-8").read())
ok("⑥ 회차당 상한이 15 이다", re.search(r"DEFAULT_TEST_CAP\s*=\s*15\b", CAP) is not None)

# ── 조기 종료 계약 — 서버가 targets 를 실어 보내는가 ─────────────────────
print("\n[계약 — 서버가 확장에 목표를 내려보낸다]")
CO = code(COLL)
ok("서버 /keywords 가 targets 를 싣는다", CO.count('"targets": _targets(conn,') == 2)
ok("두 갈래(hourly·all) 모두에 실린다",
   '"mode": "all"' in CO and '"mode": "hourly"' in CO)
ok("🔴 조회가 깨져도 수집이 멈추지 않는다(빈 dict 폴백)",
   "def _targets(" in CO and "return {}" in CO[CO.index("def _targets("):CO.index("def _targets(") + 900])

# ── 깊이 300 — 확장·서버 양쪽 표기 ───────────────────────────────────────
print("\n[깊이 300 — 대표 확정]")
ok("확장 깊이가 300 이다", re.search(r"maxRank:\s*300", EXT) is not None)
ok("확장 페이지 수가 8장이다", re.search(r"pagesPerKeyword:\s*8", EXT) is not None)
ok("🔴 400·11장이 남아 있지 않다(되돌림 방어)",
   re.search(r"maxRank:\s*400", EXT) is None
   and re.search(r"pagesPerKeyword:\s*11", EXT) is None)

print(f"\n{'❌ 실패 ' + str(_f) if _f else '✅'} 통과 {_p} · 실패 {_f}")
sys.exit(1 if _f else 0)
