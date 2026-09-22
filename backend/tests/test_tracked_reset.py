"""회귀 — 추적 상품 전량 소프트 내리기 (대표 확정 2026-09-21 · 부팅 1회) + 재등록 자동 복귀

지키는 것:
  ① 내리기는 disabled_at 만 찍는다 — rankings·tracked_keywords·rank_link 행수 불변(이력 보존).
  ② 마커로 1회만 돈다 · 실패하면 마커를 안 남긴다.
  ③ 같은 상품을 다시 등록하면 disabled_at 이 풀려 이력이 이어진다(add_tracked_product).
  ④ 하단 목록(get_all_tracked_products)·상세 카드(rank_board products)는 내려진 상품을 뺀다.
  ⑤ 부팅 잡에 등록돼 있다.

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없다. scheduler 함수는 소스에서 잘라 실행한다(기존 정리 시험과 같은 방식).
"""
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


SRC = open(os.path.join(BACKEND, "scheduler.py"), encoding="utf-8").read()
i = SRC.find("def _run_tracked_reset_20260922(")
j = SRC.find("\ndef ", i + 10)
FN = SRC[i:j]
MARK = re.search(r'_TRACKED_RESET_MARKER_NAME\s*=\s*"([^"]+)"', SRC).group(1)

SCHEMA = """
CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT, product_name TEXT, store_name TEXT,
  image_url TEXT, price INTEGER, product_id TEXT, user_id INTEGER DEFAULT 0, nv_mid TEXT DEFAULT '',
  disabled_at TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')), updated_at TEXT);
CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INTEGER, keyword TEXT,
  FOREIGN KEY(product_id) REFERENCES tracked_products(id) ON DELETE CASCADE);
CREATE TABLE rankings(id INTEGER PRIMARY KEY, product_id INTEGER, keyword_id INTEGER, keyword TEXT,
  rank_position INTEGER, page_number INTEGER, check_type TEXT, checked_at TEXT,
  FOREIGN KEY(product_id) REFERENCES tracked_products(id) ON DELETE CASCADE);
CREATE TABLE rank_link(id INTEGER PRIMARY KEY, client_id INTEGER, tracked_product_id INTEGER, keyword_id INTEGER);
"""


def seed(db):
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO tracked_products(id,product_url,user_id,disabled_at) VALUES(?,?,?,?)",
                  [(1, "https://smartstore.naver.com/a/products/1", 7, ""),
                   (2, "https://smartstore.naver.com/b/products/2", 7, ""),
                   (3, "https://smartstore.naver.com/c/products/3", 8, "2026-09-01 00:00:00")])
    c.executemany("INSERT INTO tracked_keywords(id,product_id,keyword) VALUES(?,?,?)",
                  [(10, 1, "김치"), (11, 2, "사과"), (12, 3, "배")])
    c.executemany("INSERT INTO rankings(product_id,keyword_id,keyword,rank_position,check_type,checked_at) VALUES(?,?,?,?,?,?)",
                  [(1, 10, "김치", 12, "scheduled", "2026-09-20 08:00:00"),
                   (1, 10, "김치", 11, "scheduled", "2026-09-21 08:00:00"),
                   (2, 11, "사과", None, "scheduled", "2026-09-21 08:00:00")])
    c.execute("INSERT INTO rank_link(client_id,tracked_product_id,keyword_id) VALUES(100,1,10)")
    c.commit(); c.close()


class _L:
    def __init__(self): self.lines = []
    def info(self, m): self.lines.append(("I", m))
    def error(self, m): self.lines.append(("E", m))
    def warning(self, m): self.lines.append(("W", m))


def run_fn(db):
    os.environ["DB_PATH"] = db
    g = {"logger": _L(), "_TRACKED_RESET_MARKER_NAME": MARK}
    exec(FN, g)
    g["_run_tracked_reset_20260922"]()
    return g["logger"]


print("① 내리기 — disabled_at 만 찍고 이력은 그대로")
with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "t.db"); seed(db)
    before = sqlite3.connect(db).execute("SELECT (SELECT COUNT(*) FROM rankings),(SELECT COUNT(*) FROM tracked_keywords),(SELECT COUNT(*) FROM rank_link)").fetchone()
    log = run_fn(db)
    c = sqlite3.connect(db)
    act = c.execute("SELECT COUNT(*) FROM tracked_products WHERE COALESCE(disabled_at,'')=''").fetchone()[0]
    after = c.execute("SELECT (SELECT COUNT(*) FROM rankings),(SELECT COUNT(*) FROM tracked_keywords),(SELECT COUNT(*) FROM rank_link)").fetchone()
    tot = c.execute("SELECT COUNT(*) FROM tracked_products").fetchone()[0]
    ok("🔴 활성 상품이 0개가 된다", act == 0, f"active={act}")
    ok("🔴 상품 행은 지우지 않는다(3개 그대로)", tot == 3)
    ok("🔴 rankings·tracked_keywords·rank_link 행수 불변", before == after, f"{before}→{after}")
    ok("이미 내려진 상품의 disabled_at 은 덮지 않는다",
       c.execute("SELECT disabled_at FROM tracked_products WHERE id=3").fetchone()[0] == "2026-09-01 00:00:00")
    ok("마커를 남긴다", os.path.exists(os.path.join(d, MARK)))
    ok("완료 로그에 내린 수·보존 이력 수가 찍힌다",
       any("2개 내림" in m and "3행 보존" in m for k, m in log.lines if k == "I"))
    c.close()
    # 두 번째 실행 = 무동작
    c = sqlite3.connect(db); c.execute("UPDATE tracked_products SET disabled_at='' WHERE id=1"); c.commit(); c.close()
    run_fn(db)
    ok("② 마커가 있으면 다시 돌지 않는다(되살린 1개가 그대로)",
       sqlite3.connect(db).execute("SELECT COUNT(*) FROM tracked_products WHERE COALESCE(disabled_at,'')=''").fetchone()[0] == 1)

print("\n② 실패 시 마커 미생성 · 표 없으면 건너뜀")
with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "t.db"); sqlite3.connect(db).close()
    log = run_fn(db)
    ok("빈 DB 는 건너뛰고 마커를 안 남긴다", not os.path.exists(os.path.join(d, MARK)))
ok("🔴 함수가 DELETE 문을 쓰지 않는다(UPDATE 만)", "DELETE FROM" not in FN and "UPDATE tracked_products SET disabled_at" in FN)
ok("함수가 이력 행수 변동을 감시한다", "hist_after != hist_before" in FN)

print("\n③ 재등록하면 내려 둔 상태가 풀린다 (add_tracked_product)")
with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "t.db"); seed(db)
    run_fn(db)
    os.environ["DB_PATH"] = db
    sys.path.insert(0, BACKEND)
    for m in list(sys.modules):
        if m in ("database", "nvmid"): del sys.modules[m]
    import database as DBM
    DBM.DB_PATH = db
    pid = DBM.add_tracked_product("https://smartstore.naver.com/a/products/1", product_name="A", user_id=7, nv_mid="12345678901")
    row = sqlite3.connect(db).execute("SELECT id, COALESCE(disabled_at,''), nv_mid FROM tracked_products WHERE id=1").fetchone()
    ok("🔴 같은 URL·같은 사용자 재등록 = 같은 id 로 복귀(새 행 아님)", pid == 1)
    ok("🔴 disabled_at 이 비워진다", row[1] == "")
    ok("nvMid 는 새 값으로 채워진다", row[2] == "12345678901")
    ok("이력(rankings)이 그대로 이어진다",
       sqlite3.connect(db).execute("SELECT COUNT(*) FROM rankings WHERE product_id=1").fetchone()[0] == 2)
    lst = DBM.get_all_tracked_products(user_id=7, is_admin=True)
    ok("🔴 하단 목록은 내려진 상품을 뺀다(복귀한 1개만)", [p["id"] for p in lst] == [1], str([p["id"] for p in lst]))
    lst2 = DBM.get_all_tracked_products(user_id=7, is_admin=False)
    ok("사용자별 목록도 내려진 상품을 뺀다", [p["id"] for p in lst2] == [1])

print("\n④ 상세 카드(rank_board)가 내려진 상품을 뺀다 · ⑤ 부팅 잡 등록")
cd = open(os.path.join(BACKEND, "client_dashboard.py"), encoding="utf-8").read()
ok("🔴 rank_board 상품 루프가 내려진 상품에서 continue 한다",
   re.search(r"if _dis:\s*\n\s*continue[\s\S]{0,200}products\.append\(", cd) is not None)
ok("🔴 부팅 잡으로 등록돼 있다",
   "_run_tracked_reset_20260922," in SRC and 'id="tracked_reset_20260922_boot"' in SRC)
ok("마커 이름이 날짜를 담는다", "20260922" in MARK)

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
