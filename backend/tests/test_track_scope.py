"""회귀 — 순위 추적 대상 기준 (대표 확정 2026-09-18)

지키는 것 셋:
  ① 자격은 **계약 단계 「진행중」** 을 직접 본다 (동기화가 안 돌아도 걸러진다)
  ② 수집 유니버스에서 **분석 이력(client_analyses)** 을 쓰지 않는다
  ③ 키워드는 **최대 5개**까지만 손으로 추가된다

⚠️ 표준 라이브러리만 쓴다 — 배포 게이트 환경에 fastapi 가 없다.
   그래서 collector.py·main.py 는 import 하지 않고 **소스를 읽어** 배선을 확인한다.
"""

import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

import keyword_limit                      # noqa: E402
import tracking_eligibility as TE         # noqa: E402

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def src(rel):
    with open(os.path.join(BACKEND, rel), encoding="utf-8") as f:
        return f.read()


def make_db():
    """자격 판정을 실제로 돌려 볼 최소 DB."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE clients(
            id INTEGER PRIMARY KEY, name TEXT, status TEXT DEFAULT 'active',
            role TEXT DEFAULT 'advertiser', vertical TEXT DEFAULT 'store',
            auto_analysis INTEGER DEFAULT 1, track_enabled INTEGER DEFAULT 1,
            track_until TEXT, main_keywords TEXT DEFAULT '');
        CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT);
        CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INTEGER, keyword TEXT);
        CREATE TABLE rank_link(id INTEGER PRIMARY KEY, client_id INTEGER, tracked_product_id INTEGER);
    """)
    return conn


print("① 자격 — 계약 단계 「진행중」을 직접 본다")

ok("상수 TRACK_STAGE 가 '진행중' 이다", getattr(TE, "TRACK_STAGE", None) == "진행중",
   f"실제 {getattr(TE, 'TRACK_STAGE', None)!r}")
ok("ELIGIBLE_WHERE 가 contract_stage 를 본다", "contract_stage" in TE.ELIGIBLE_WHERE)
ok("🔴 조건식 자체가 남아 있다(문구만 남기고 무력화 방어)",
   re.search(r"TRIM\(COALESCE\(contract_stage,''\)\)\s*=\s*'진행중'", TE.ELIGIBLE_WHERE) is not None,
   "조건식이 사라졌다")
ok("ensure_stage_column 이 있다", callable(getattr(TE, "ensure_stage_column", None)))

conn = make_db()
TE.ensure_stage_column(conn)
cols = {r[1] for r in conn.execute("PRAGMA table_info(clients)")}
ok("ensure_stage_column 이 칸을 만든다", "contract_stage" in cols)
TE.ensure_stage_column(conn)   # 두 번 돌려도 안 깨진다
ok("ensure_stage_column 은 멱등이다", True)

conn.executemany(
    "INSERT INTO clients(id,name,contract_stage,main_keywords) VALUES(?,?,?,?)",
    [(1, "가", "진행중", "가키워드"),
     (2, "나", "홀딩중", "나키워드"),
     (3, "다", "계약 만료", "다키워드"),
     (4, "라", "환불중", "라키워드"),
     (5, "마", "사후 관리", "마키워드"),
     (6, "바", None, "바키워드"),
     (7, "사", "", "사키워드"),
     (8, "아", "  진행중  ", "아키워드")])
conn.commit()

ids = TE.eligible_client_ids(conn)
ok("진행중만 통과한다", set(ids) == {1, 8}, f"실제 {sorted(ids)}")
ok("홀딩중은 빠진다", 2 not in ids)
ok("계약 만료는 빠진다", 3 not in ids)
ok("환불중은 빠진다", 4 not in ids)
ok("사후 관리는 빠진다(대표 확정 「진행중만」)", 5 not in ids)
ok("단계 없음(NULL)은 빠진다", 6 not in ids)
ok("단계 빈 문자열은 빠진다", 7 not in ids)
ok("앞뒤 공백이 있어도 진행중으로 본다", 8 in ids)

# 기존 6조건이 살아 있나 — 하나라도 빠지면 계약 끝난 업체가 되살아난다
conn.execute("UPDATE clients SET status='terminated' WHERE id=1")
conn.commit()
ok("내린 업체는 진행중이어도 빠진다", 1 not in TE.eligible_client_ids(conn))
conn.execute("UPDATE clients SET status='active', auto_analysis=0 WHERE id=1")
conn.commit()
ok("자동분석 OFF 면 진행중이어도 빠진다", 1 not in TE.eligible_client_ids(conn))
conn.execute("UPDATE clients SET auto_analysis=1, track_until='2000-01-01' WHERE id=1")
conn.commit()
ok("추적 기간이 지났으면 빠진다", 1 not in TE.eligible_client_ids(conn))
conn.execute("UPDATE clients SET track_until=NULL, role='prospect' WHERE id=1")
conn.commit()
ok("영업 대상은 빠진다", 1 not in TE.eligible_client_ids(conn))
conn.execute("UPDATE clients SET role='advertiser', vertical='place' WHERE id=1")
conn.commit()
ok("플레이스는 빠진다", 1 not in TE.eligible_client_ids(conn))
conn.close()

# 자격 0곳이어도 죽지 않는다
conn2 = make_db()
ok("자격 0곳이면 빈 목록을 돌려준다(예외 아님)", TE.eligible_client_ids(conn2) == [])
conn2.close()


print("\n② 수집 유니버스 — 분석 이력을 쓰지 않는다")

col = src("collector.py")
uni = col[col.index("def _keyword_universe"):]
uni = uni[:uni.index("\ndef ", 10)]
live = "\n".join(ln for ln in uni.split("\n") if not ln.strip().startswith("#"))

# ⚠️ 판정 기준을 **조회문**으로 좁힌다. 이름만 찾으면 독스트링의 설명 줄
#    (「② client_analyses — 제외」)까지 걸려 멀쩡한 코드를 고장으로 읽는다.
#    실제로 처음에 그렇게 걸렸다 — 이 저장소가 반복하는 함정(문구 vs 동작)이다.
ok("🔴 살아 있는 코드에 client_analyses **조회**가 없다",
   "FROM client_analyses" not in live, "분석 이력이 아직 수집 대상을 만든다")
ok("🔴 살아 있는 코드에 그 조회를 실행하는 자리가 없다",
   not re.search(r"^\s*(?!#).*conn\.execute\([^)]*client_analyses", live, re.M))
ok("원본은 주석으로 남겨 뒀다(되돌릴 근거)", "FROM client_analyses" in uni)
ok("① 대표 키워드는 그대로 쓴다", "main_keywords" in live)
ok("③ 추적 상품 키워드는 그대로 쓴다", "tracked_keywords" in live)
ok("자격 판정을 지난다", "_tracking_client_ids" in live)


print("\n③ 키워드 상한 — 최대 5개")

ok("상한이 5 다", keyword_limit.MAX_MANUAL_KEYWORDS == 5,
   f"실제 {keyword_limit.MAX_MANUAL_KEYWORDS}")
ok("0개에서 1개 추가 가능", keyword_limit.can_add(0, 1))
ok("4개에서 1개 추가 가능", keyword_limit.can_add(4, 1))
ok("5개에서 1개 추가 불가", not keyword_limit.can_add(5, 1))
ok("6개에서 1개 추가 불가", not keyword_limit.can_add(6, 1))
ok("3개에서 2개 한꺼번에 가능", keyword_limit.can_add(3, 2))
ok("3개에서 3개 한꺼번에 불가", not keyword_limit.can_add(3, 3))
ok("🔴 세기 실패(-1)면 막지 않는다(fail-open)", keyword_limit.can_add(-1, 1))
ok("이상한 값이 와도 막지 않는다", keyword_limit.can_add(None, 1))
ok("남은 개수 — 0개면 5", keyword_limit.remaining(0) == 5)
ok("남은 개수 — 5개면 0", keyword_limit.remaining(5) == 0)
ok("남은 개수 — 음수면 상한 그대로", keyword_limit.remaining(-1) == 5)

conn3 = make_db()
conn3.execute("INSERT INTO tracked_products(id,product_url) VALUES(1,'u')")
for i, k in enumerate(["가", "나", "다"], start=1):
    conn3.execute("INSERT INTO tracked_keywords(id,product_id,keyword) VALUES(?,1,?)", (i, k))
conn3.commit()
ok("상품 키워드 수를 센다", keyword_limit.count_for_product(conn3, 1) == 3)
ok("없는 상품은 0", keyword_limit.count_for_product(conn3, 99) == 0)

conn3.execute("INSERT INTO rank_link(client_id,tracked_product_id) VALUES(7,1)")
conn3.commit()
ok("업체 단위로도 셀 수 있다(나중에 갈아 끼울 자리)",
   keyword_limit.count_for_client(conn3, 7) == 3)
conn3.close()

db = src("database.py")
ok("add_tracked_keyword 가 상한을 건다", "keyword_limit" in db and "can_add" in db)
ok("🔴 상한 호출이 살아 있다(문구만 남기기 방어)",
   re.search(r"if\s+not\s+can_add\(", db) is not None)
ok("이미 있는 키워드는 상한 전에 돌려준다(중복은 안 막는다)",
   db.index('SELECT id FROM tracked_keywords WHERE product_id') < db.index("can_add("))
ok("KeywordLimitError 를 정의한다", "class KeywordLimitError" in db)

mn = src("main.py")
ok("등록 API 가 상한 초과를 잡는다", "except KeywordLimitError" in mn)
ok("넘긴 키워드를 화면에 돌려준다", "keywords_rejected" in mn)
ok("🔴 넘겨도 나머지는 등록된다(전부 되돌리지 않는다)",
   "keyword_rejected.append" in mn and "raise" not in
   mn[mn.index("except KeywordLimitError"):mn.index("except KeywordLimitError") + 200])

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
