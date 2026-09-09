#!/usr/bin/env python3
"""
채팅 참고 자료(RAG)의 업체 범위 시험 — 표준 라이브러리만 (2026-09-08)

## 왜 이 시험이 있나
업체 화면은 `client_dashboard._verify_client_access` 로 「admin 은 전체 ·
그 외는 본인이 등록한 업체만」을 막는다. 그런데 **채팅의 참고 자료 조회에만
그 판정이 없어서**, 업체 이름만 넣으면 담당 아닌 업체의 상호·주요 키워드·
최근 순위·분석 이력이 AI 답변에 실려 나갔다(2026-09-08 전수 점검).

## 어떻게 검사하나
배포 게이트 환경에는 fastapi·anthropic 이 없어 chat.py 를 임포트할 수 없다.
그래서 **소스에서 판정 함수 두 개만 뽑아 그대로 실행**한다(복사본이 아니라 진짜 코드다).
그 판정이 만든 조건을 실제 표에 걸어 「누가 무엇을 보는가」를 확인하고,
마지막에 다섯 조회 자리에 그 조건이 실제로 붙어 있는지 소스로 확인한다.

한 자리라도 조건을 떼면 이 시험이 깨진다.
"""
import ast
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHAT_PY = os.path.join(HERE, "..", "chat.py")

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILED.append(name)


def load_real_predicates():
    """chat.py 소스에서 _is_admin·_client_scope 함수만 뽑아 실행한다.

    복사본을 두면 원본이 바뀌어도 시험은 통과한다 — 그래서 진짜 소스를 쓴다.
    """
    with open(CHAT_PY, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    wanted = {"_is_admin", "_client_scope"}
    picked = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in wanted]
    missing = wanted - {n.name for n in picked}
    if missing:
        raise AssertionError(f"chat.py 에서 판정 함수를 못 찾았다: {sorted(missing)}")
    mod = ast.Module(body=picked, type_ignores=[])
    ns = {}
    exec(compile(mod, "chat_predicates", "exec"), ns)   # noqa: S102 — 우리 소스다
    return src, ns["_is_admin"], ns["_client_scope"]


def build_db():
    """업체 3곳 — 등록자가 서로 다르다."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY, name TEXT, business_name TEXT,
            main_keywords TEXT, status TEXT, created_by INTEGER);
        CREATE TABLE client_analyses (
            id INTEGER PRIMARY KEY, client_id INTEGER, keyword TEXT, analyzed_date TEXT);
        CREATE TABLE client_rank_history (
            id INTEGER PRIMARY KEY, client_id INTEGER, keyword TEXT,
            rank_position INTEGER, checked_at TEXT);
    """)
    conn.executemany(
        "INSERT INTO clients (id,name,business_name,main_keywords,status,created_by) VALUES (?,?,?,?,?,?)",
        [(1, "가나상회", "가나상회", "김치,만두", "active", 10),      # 등록자 10
         (2, "다라식품", "다라식품", "김치,젓갈", "active", 20),      # 등록자 20
         (3, "마바유통", "마바유통", "청귤", "active", 20)])          # 등록자 20
    conn.executemany(
        "INSERT INTO client_analyses (client_id,keyword,analyzed_date) VALUES (?,?,?)",
        [(1, "김치", "2026-09-08"), (2, "김치", "2026-09-08"), (3, "청귤", "2026-09-08")])
    conn.executemany(
        "INSERT INTO client_rank_history (client_id,keyword,rank_position,checked_at) VALUES (?,?,?,?)",
        [(1, "김치", 12, "2026-09-08 08:00"), (2, "김치", 30, "2026-09-08 08:00")])
    conn.commit()
    return conn


def names_for(conn, scope_sql, scope_args, kw="김치"):
    """키워드 분석 이력 조회 — chat.py 와 같은 모양."""
    rows = conn.execute(
        "SELECT c.name AS client_name FROM client_analyses ca"
        " JOIN clients c ON ca.client_id = c.id"
        " WHERE ca.keyword LIKE ?" + scope_sql,
        (f"%{kw}%",) + scope_args).fetchall()
    return sorted(r["client_name"] for r in rows)


def rank_names_for(conn, scope_sql, scope_args, kw="김치"):
    rows = conn.execute(
        "SELECT c.name AS client_name FROM client_rank_history crh"
        " JOIN clients c ON crh.client_id = c.id"
        " WHERE crh.keyword LIKE ?" + scope_sql,
        (f"%{kw}%",) + scope_args).fetchall()
    return sorted(r["client_name"] for r in rows)


def lookup(conn, scope_sql, scope_args, term):
    row = conn.execute(
        "SELECT c.id, c.name, c.main_keywords FROM clients c"
        " WHERE (c.name LIKE ? OR c.business_name LIKE ?)" + scope_sql + " LIMIT 1",
        (f"%{term}%", f"%{term}%") + scope_args).fetchone()
    return row["name"] if row else None


def main():
    print("채팅 참고 자료 범위 시험")
    src, is_admin, client_scope = load_real_predicates()
    conn = build_db()

    admin = {"id": 1, "role": "admin"}
    boss = {"id": 2, "role": "superadmin"}
    a = {"id": 10, "role": "viewer"}     # 가나상회 등록자
    b = {"id": 20, "role": "manager"}    # 다라식품·마바유통 등록자
    stranger = {"id": 99, "role": "manager"}
    anon = None

    # ① 판정 자체
    check("① admin 은 조건이 안 붙는다", client_scope(admin) == ("", ()))
    check("①-보조 superadmin 도 전체", client_scope(boss) == ("", ()))
    check("① viewer 는 본인 조건", client_scope(a) == (" AND c.created_by = ?", (10,)))
    check("① manager 도 본인 조건", client_scope(b) == (" AND c.created_by = ?", (20,)))
    check("① 누군지 모르면 아무것도 안 준다", client_scope(anon) == (" AND 1=0", ()),
          f"실제={client_scope(anon)}")
    check("①-보조 id 없는 사용자도 차단", client_scope({"role": "manager"}) == (" AND 1=0", ()))
    check("①-보조 _is_admin 은 두 역할만", is_admin(admin) and is_admin(boss)
          and not is_admin(a) and not is_admin(b) and not is_admin(anon))

    # ② 분석 이력 — 같은 키워드를 두 업체가 쓴다
    check("② admin 은 김치를 쓰는 두 업체를 다 본다",
          names_for(conn, *client_scope(admin)) == ["가나상회", "다라식품"])
    check("② 등록자 A 는 자기 것만", names_for(conn, *client_scope(a)) == ["가나상회"])
    check("② 등록자 B 는 자기 것만", names_for(conn, *client_scope(b)) == ["다라식품"])
    check("② 남의 담당은 한 건도 안 나온다",
          "다라식품" not in names_for(conn, *client_scope(a)))
    check("② 아무 업체도 없는 사람은 0건", names_for(conn, *client_scope(stranger)) == [])
    check("② 로그인 판정 실패 시 0건", names_for(conn, *client_scope(anon)) == [])

    # ③ 순위 이력
    check("③ admin 은 순위도 둘 다", rank_names_for(conn, *client_scope(admin)) == ["가나상회", "다라식품"])
    check("③ 등록자 A 는 순위도 자기 것만", rank_names_for(conn, *client_scope(a)) == ["가나상회"])

    # ④ 업체 이름으로 찾기 — 신고의 실제 경로
    check("④ admin 은 이름으로 찾힌다", lookup(conn, *client_scope(admin), "다라") == "다라식품")
    check("④ 남의 업체는 이름을 알아도 안 나온다", lookup(conn, *client_scope(a), "다라") is None)
    check("④ 자기 업체는 그대로 나온다", lookup(conn, *client_scope(a), "가나") == "가나상회")
    check("④ 등록자 B 는 자기 업체 둘 다", lookup(conn, *client_scope(b), "마바") == "마바유통")

    # ⑤ 현황 요약 — 규모 숫자도 새면 안 된다
    def active_count(scope_sql, scope_args):
        return conn.execute(
            "SELECT COUNT(*) n FROM clients c WHERE c.status='active'" + scope_sql,
            scope_args).fetchone()["n"]
    check("⑤ admin 활성 업체 3", active_count(*client_scope(admin)) == 3)
    check("⑤ 등록자 A 활성 업체 1", active_count(*client_scope(a)) == 1)
    check("⑤ 등록자 B 활성 업체 2", active_count(*client_scope(b)) == 2)

    # ⑥ 소스에 조건이 실제로 붙어 있나 — 한 자리만 떼도 깨진다
    check("⑥ 참고 자료 조회가 current_user 를 받는다",
          "def _fetch_context_data(message: str, current_user: dict)" in src)
    check("⑥ 호출부가 current_user 를 넘긴다",
          "_fetch_context_data(message, current_user)" in src)
    check("⑥ 기본값이 없다(새 호출처가 그냥 지나갈 수 없다)",
          "_fetch_context_data(message: str, current_user: dict = " not in src)
    n_scope = src.count("scope_sql")
    check(f"⑥ 조회 자리에 조건이 붙어 있다 (scope_sql {n_scope}회)", n_scope >= 8,
          f"실제 {n_scope}회 — 조회 자리에서 조건이 빠졌는지 확인할 것")
    for site, needle in [
        ("분석 이력", 'WHERE ca.keyword LIKE ?""" + scope_sql'),
        ("순위 이력", 'WHERE crh.keyword LIKE ?""" + scope_sql'),
        ("업체 이름 찾기", 'c.business_name LIKE ?)""" + scope_sql'),
        ("현황 요약", '"   WHERE c.status = \'active\'" + scope_sql'),
        ("키워드 TOP 10", '" WHERE 1=1" + scope_sql'),
    ]:
        check(f"⑥-{site} 자리에 조건이 있다", needle in src)

    conn.close()
    print()
    if FAILED:
        print(f"❌ 실패 {len(FAILED)}건: {FAILED}")
        return 1
    print("채팅 범위 시험 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
