"""회귀 — 순위 추적 3탭 분리 (대표 확정 2026-09-22 · 시안 v1)

지키는 것:
  ① rank_axes 가 두 축(대표 키워드·담당자 키워드)을 실제 표에서 바르게 나눈다
     — 내려진 상품 제외 · 자격 판정 · 옛 DB(칸 없음) 관용 · 겹치는 키워드는 양쪽에.
  ② rank_overview 가 축 값(axes·auto_keywords·manual_products·eligible·contract_stage·totals.tabs)을
     additive 로 내려주고, rank_board 행에 sources(속한 축 전부)가 실린다.
  ③ 화면(KeywordRankPage)에 탭 3개 · 탭 소속 규칙(서버와 동일) · 펼침 카드 축 필터 · 브라우저 기억 · 빈 상태 문구.
  ④ 「300위 밖」 표기는 그대로(대표 확정 — 「순위 미확인」으로 바꾸지 않는다).

⚠️ 게이트 환경엔 fastapi 가 없다 → ①은 rank_axes 를 직접 import(stdlib 만), ②③은 소스 배선으로 판정.
   이름만 찾으면 주석에 걸리므로 **호출 모양·조건식**으로 본다.
"""
import os
import re
import sqlite3
import sys
import tempfile

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


SCHEMA = """
CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT, status TEXT DEFAULT 'active', role TEXT DEFAULT 'advertiser',
  vertical TEXT DEFAULT 'store', auto_analysis INTEGER DEFAULT 1, track_enabled INTEGER DEFAULT 1, track_until TEXT,
  contract_stage TEXT, main_keywords TEXT DEFAULT '');
CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT, disabled_at TEXT DEFAULT '');
CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INTEGER, keyword TEXT);
CREATE TABLE rank_link(id INTEGER PRIMARY KEY, client_id INTEGER, tracked_product_id INTEGER);
"""


def make_db(schema=SCHEMA):
    d = tempfile.mkdtemp()
    c = sqlite3.connect(os.path.join(d, "t.db"))
    c.executescript(schema)
    c.executemany("INSERT INTO clients(id,name,contract_stage,main_keywords,auto_analysis) VALUES(?,?,?,?,?)", [
        (1, "가", "진행중", "가오리회무침, 간재미무침", 1),   # 대표 2 + 담당자 2(겹침)
        (2, "나", "진행중", "", 1),                          # 대표 0 · 담당자 1 (자격은 있음)
        (3, "다", "홀딩중", "냉동딸기", 1),                  # 자격 없음(단계) · 대표 1
        (4, "라", "진행중", "전복죽", 0),                    # 자격 없음(자동분석 OFF)
        (5, "마", "진행중", "배", 1),                        # 담당자 상품은 있으나 내려짐
    ])
    c.executemany("INSERT INTO tracked_products(id,product_url,disabled_at) VALUES(?,?,?)", [
        (10, "u10", ""), (11, "u11", ""), (12, "u12", "2026-09-22 10:41:00")])
    c.executemany("INSERT INTO tracked_keywords(product_id,keyword) VALUES(?,?)", [
        (10, "간재미무침"), (10, "가오리 회무침"), (11, "사과"), (12, "배")])
    c.executemany("INSERT INTO rank_link(client_id,tracked_product_id) VALUES(?,?)", [
        (1, 10), (2, 11), (5, 12)])
    c.commit()
    return c


print("① rank_axes — 축 분리 (가짜 DB)")
import rank_axes as rx
conn = make_db()
reg = rx.registered_axes(conn, [1, 2, 3, 4, 5])
ok("🔴 대표 키워드는 main_keywords 에서 (업체1 = 2개)", reg[1]["auto_kws"] == {"가오리회무침", "간재미무침"})
ok("🔴 담당자 키워드는 이어진 상품의 tracked_keywords 에서 (업체1 = 2개 · 공백 변형 정규화)",
   reg[1]["manual_kws"] == {"간재미무침", "가오리회무침"})
ok("🔴 겹치는 키워드는 양쪽 축에 다 있다", "간재미무침" in reg[1]["auto_kws"] and "간재미무침" in reg[1]["manual_kws"])
ok("🔴 내려진 상품(disabled_at)의 키워드는 담당자 축에서 빠진다 (업체5 = 0)",
   reg[5]["manual_kws"] == set() and reg[5]["manual_products"] == 0)
ok("살아 있는 상품 수 (업체1 = 1 · 업체2 = 1)", reg[1]["manual_products"] == 1 and reg[2]["manual_products"] == 1)
ok("🔴 자격 판정 — 진행중·자동분석 ON 만 True", reg[1]["eligible"] is True and reg[2]["eligible"] is True
   and reg[3]["eligible"] is False and reg[4]["eligible"] is False)
ok("계약 단계를 그대로 내려준다", reg[3]["contract_stage"] == "홀딩중")
ok("빈 목록이면 빈 dict", rx.registered_axes(conn, []) == {})

# 옛 DB — contract_stage · disabled_at 칸이 없다 → 죽지 않고 eligible=None · 상품 전부 살아 있음으로
OLD = """
CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT, status TEXT DEFAULT 'active', role TEXT DEFAULT 'advertiser',
  vertical TEXT DEFAULT 'store', auto_analysis INTEGER DEFAULT 1, track_enabled INTEGER DEFAULT 1, track_until TEXT,
  main_keywords TEXT DEFAULT '');
CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT);
CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INTEGER, keyword TEXT);
CREATE TABLE rank_link(id INTEGER PRIMARY KEY, client_id INTEGER, tracked_product_id INTEGER);
"""
d2 = tempfile.mkdtemp(); c2 = sqlite3.connect(os.path.join(d2, "o.db")); c2.executescript(OLD)
c2.execute("INSERT INTO clients(id,name,main_keywords) VALUES(9,'옛','김치')")
c2.execute("INSERT INTO tracked_products(id,product_url) VALUES(90,'u')")
c2.execute("INSERT INTO tracked_keywords(product_id,keyword) VALUES(90,'배')")
c2.execute("INSERT INTO rank_link(client_id,tracked_product_id) VALUES(9,90)")
c2.commit()
r9 = rx.registered_axes(c2, [9])[9]
ok("🔴 옛 DB(칸 없음)에서도 죽지 않는다 — eligible=None · 단계 빈 값", r9["eligible"] is None and r9["contract_stage"] == "")
ok("옛 DB 에선 disabled_at 필터 없이 상품을 센다", r9["manual_products"] == 1 and r9["manual_kws"] == {"배"})

st = rx.new_stat()
rx.add_stat(st, 5, 8, "2026-09-22")     # 노출·TOP10·상승
rx.add_stat(st, None, None, "2026-09-21")   # 미노출
rx.add_stat(st, 30, 20, "2026-09-22")   # 하락
ok("🔴 축 집계 규칙 = rank_overview 와 동일(키워드3·노출2·TOP10 1·▲1·▼1·최근일)",
   st == {"keywords": 3, "exposed": 2, "top10": 1, "up": 1, "down": 1, "last_checked": "2026-09-22"})
pay = rx.axes_payload(reg[1], None, None)
ok("axes_payload 가 registered(등록 수)·products 를 함께 준다",
   pay["client"]["registered"] == 2 and pay["product"]["registered"] == 2 and pay["product"]["products"] == 1)
ok("🔴 탭 소속 — auto = 자격 · 자격 모르면 대표 키워드 유무",
   rx.in_tab({"eligible": True, "auto_keywords": 0}, "auto") is True
   and rx.in_tab({"eligible": False, "auto_keywords": 3}, "auto") is False
   and rx.in_tab({"eligible": None, "auto_keywords": 1}, "auto") is True
   and rx.in_tab({"eligible": None, "auto_keywords": 0}, "auto") is False)
ok("🔴 탭 소속 — manual = 살아 있는 상품 1개 이상", rx.in_tab({"manual_products": 1}, "manual") and not rx.in_tab({"manual_products": 0}, "manual"))

print("\n② BE 배선 — rank_overview · rank_board")
cd = read("backend/client_dashboard.py")
i = cd.index("def rank_overview("); ov = cd[i:cd.index("\ndef rank_board(", i)]
ok("🔴 rank_overview 가 rank_axes.registered_axes 를 부른다", re.search(r"_rx\.registered_axes\(conn,\s*ids\)", ov) is not None)
ok("🔴 (업체,키워드)마다 대표 축·담당자 축에 각각 add_stat 한다(겹치면 둘 다)",
   re.search(r'if _nk in _reg\[cid\]\["auto_kws"\]:\s*\n\s*_rx\.add_stat\(_ax\["client"\]', ov) is not None
   and re.search(r'if _nk in _reg\[cid\]\["manual_kws"\]:\s*\n\s*_rx\.add_stat\(_ax\["product"\]', ov) is not None)
ok("🔴 업체 항목에 axes·auto_keywords·manual_products·eligible·contract_stage 를 additive 로 넣는다",
   all(re.search(rf'item\["{k}"\]\s*=', ov) for k in ("axes", "auto_keywords", "manual_keywords", "manual_products", "eligible", "contract_stage")))
ok("🔴 totals.tabs 가 in_tab 으로 센다", re.search(r'totals\["tabs"\][\s\S]{0,200}_rx\.in_tab\(i, "auto"\)[\s\S]{0,120}_rx\.in_tab\(i, "manual"\)', ov) is not None)
ok("축 조회 실패 시 전체 탭은 그대로 그린다(폴백)", "_rx, _reg = None, {}" in ov)
j = cd.index("def rank_board("); bd = cd[j:cd.index("\n@router", j) if "\n@router" in cd[j:] else len(cd)]
ok("🔴 rank_board 행 출처가 sources(속한 축 전부)를 함께 준다",
   re.search(r'if k in _mk_set:\s*\n\s*srcs\.append\("client"\)\s*\n\s*if k in _prod_kw:\s*\n\s*srcs\.append\("product"\)', bd) is not None
   and bd.count('"sources": srcs') == 3)
ok("종전 source 우선순위(업체>상품>이력)는 그대로", re.search(r'return \{"source": "client", "source_label": "업체 키워드", "sources": srcs\}', bd) is not None)

print("\n③ FE 배선 — KeywordRankPage 3탭")
fe = read("frontend/js/components/KeywordRankPage.jsx")
ok("🔴 탭 버튼 3개(전체·로직분석 대표 키워드·담당자 추가 키워드)",
   all(f"tabBtn('{k}', '{l}')" in fe for k, l in (("all", "📊 전체"), ("auto", "🔗 로직분석 대표 키워드"), ("manual", "✍️ 담당자 추가 키워드"))))
ok("🔴 탭 소속 규칙이 서버와 같다(auto=eligible·모르면 대표 키워드, manual=상품 1개 이상)",
   re.search(r"if \(tab === 'auto'\) \{ if \(c\.eligible == null\) return \(c\.auto_keywords \|\| 0\) > 0; return !!c\.eligible; \}", fe) is not None
   and "if (tab === 'manual') return (c.manual_products || 0) > 0;" in fe)
ok("🔴 목록이 탭 필터를 먼저 지난다", "var tabRows = rows.filter(function(c) { return _inTab(c, rankTab); });" in fe
   and "var shown = tabRows.filter(function(c) {" in fe)
ok("🔴 행 수치는 그 탭의 축 값(_axisOf)으로 센다", "var a = _axisOf(c, rankTab);" in fe
   and re.search(r"if \(filter === 'attention'\) return a\.keywords > 0 && a\.exposed === 0;", fe) is not None)
ok("옛 서버(axes 없음)면 전체 값으로 폴백", re.search(r"var _axisOf = function\(c, tab\) \{\s*var ax = c\.axes \|\| \{\};[\s\S]{0,200}return c;", fe) is not None)
ok("🔴 펼침 카드는 sources 로 그 탭의 축만 보여준다",
   "var brd = brdAll.filter(function(b) { return _boardInTab(b, rankTab); });" in fe
   and "return srcs.indexOf(tab === 'auto' ? 'client' : 'product') !== -1;" in fe)
ok("🔴 탭을 브라우저에 기억한다(localStorage kr_rank_tab · 실패해도 동작)",
   "localStorage.getItem('kr_rank_tab')" in fe and "localStorage.setItem('kr_rank_tab', t)" in fe
   and re.search(r"catch \(e\) \{ return 'all'; \}", fe) is not None)
ok("🔴 담당자 탭 빈 상태 문구(시안)", "담당자가 추가한 키워드가 아직 없습니다." in fe
   and "같은 상품을 다시 등록하면 이전 순위 이력이 그대로 이어집니다." in fe)
ok("대표 탭은 「단계」 칸을 보인다", "rankTab === 'auto' ? '단계' : '상태'" in fe and "c.contract_stage" in fe)
ok("등록만 되고 기록 없는 축은 「첫 수집 대기」로 보인다", "'🆕 첫 수집 대기'" in fe and "_reg + ' 대기'" in fe)
ok("탭을 바꾸면 펼친 업체를 닫는다(다른 축 카드가 남지 않게)", "setRankTab(key); setExpClient(null);" in fe)

print("\n④ 표기 — 「300위 밖」 유지(대표 확정 9/22)")
ok("🔴 화면에 「300위 밖」이 있고 「순위 미확인」은 없다", "300위 밖" in fe and "순위 미확인" not in fe)

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
