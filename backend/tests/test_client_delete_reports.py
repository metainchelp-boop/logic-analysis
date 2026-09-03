"""신고 #259 (이진희) — 업체 삭제 시 「FOREIGN KEY constraint failed」 재발 방지 가드.

원인: reports 테이블은 clients(id) 를 참조하지만, 다른 세 자식
(client_analyses·client_rank_history·client_keyword_product)과 달리 ON DELETE CASCADE 가 없다.
client_dashboard.delete_client 은 foreign_keys=ON 인 연결에서 도는데 reports 를 지우지 않아,
보고서가 남아 있는 업체(계약 만료처럼 오래된 업체일수록 잘 걸린다)를 지울 때 SQLite 가
「FOREIGN KEY constraint failed」로 삭제를 막았다. 그 원문이 화면 alert 로 그대로 노출됐다.

이 테스트는 무거운 웹 스택(fastapi·auth) 없이 stdlib(sqlite3)만으로,
실제 스키마의 FK 계약을 그대로 세워 놓고:
  1) 고치기 전 삭제 순서 → FK 오류 재현
  2) 고친 삭제 순서 → 성공 + 업체·연결 경쟁사·자식(보고서 포함) 전부 제거
  3) CASCADE 세 자식은 업체 삭제만으로 자동 제거됨(그래서 reports 만 수동 처리하면 충분)
  4) 실제 소스(client_dashboard.delete_client)가 reports 를 지우는지 확인
을 고정한다. 배포 게이트와 동일하게 `python backend/tests/test_client_delete_reports.py` 로 자체 실행.
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 실제 client_dashboard.py 의 자식 테이블 FK 계약을 그대로 옮긴다(계약 자체가 시험 대상).
#   - 세 자식: ON DELETE CASCADE (client_dashboard.py init)
#   - reports: cascade 없음 (reports.py init) → 이것이 삭제를 막는다
_SCHEMA = """
    CREATE TABLE clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        role TEXT DEFAULT 'advertiser',
        competitor_of INTEGER,
        created_by INTEGER
    );
    CREATE TABLE client_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        keyword TEXT,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
    );
    CREATE TABLE client_rank_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        keyword TEXT,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
    );
    CREATE TABLE client_keyword_product (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        keyword TEXT,
        product_url TEXT,
        UNIQUE(client_id, keyword),
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
    );
    CREATE TABLE reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        title TEXT,
        keyword TEXT,
        report_data TEXT NOT NULL DEFAULT '{}',
        report_hash TEXT UNIQUE NOT NULL,
        created_by INTEGER NOT NULL,
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
"""


def _seed():
    """foreign_keys=ON 연결 + 업체 1곳(광고주) + 연결 경쟁사 1곳, 각자 보고서·분석·순위·상품."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    # 광고주 업체(10) + 그에 붙인 경쟁사(11)
    conn.execute("INSERT INTO clients(id, name, role, competitor_of, created_by) VALUES (10,'계약만료업체','advertiser',NULL,20)")
    conn.execute("INSERT INTO clients(id, name, role, competitor_of, created_by) VALUES (11,'경쟁사','competitor',10,20)")
    for cid in (10, 11):
        conn.execute("INSERT INTO client_analyses(client_id, keyword) VALUES (?,?)", (cid, "키워드"))
        conn.execute("INSERT INTO client_rank_history(client_id, keyword) VALUES (?,?)", (cid, "키워드"))
        conn.execute("INSERT INTO client_keyword_product(client_id, keyword, product_url) VALUES (?,?,?)", (cid, "키워드", "http://x"))
        # 보고서 — 이것이 cascade 없이 clients 를 참조해 삭제를 막는다
        conn.execute(
            "INSERT INTO reports(client_id, title, keyword, report_hash, created_by) VALUES (?,?,?,?,?)",
            (cid, "보고서", "키워드", f"hash-{cid}", 20),
        )
    conn.commit()
    return conn


def _linked_del_ids(conn, client_id):
    """client_dashboard.delete_client 과 동일하게 대상 업체 + 붙은 경쟁사 id 를 모은다."""
    linked = [r["id"] for r in conn.execute(
        "SELECT id FROM clients WHERE COALESCE(role,'advertiser')='competitor' AND competitor_of = ?",
        (client_id,),
    ).fetchall()]
    return [client_id] + linked


def test_old_order_reproduces_fk_error():
    """고치기 전 순서(analyses·rank_history·clients)는 보고서가 남아 FK 오류로 막힌다."""
    conn = _seed()
    raised = None
    try:
        for cid in _linked_del_ids(conn, 10):
            conn.execute("DELETE FROM client_analyses WHERE client_id = ?", (cid,))
            conn.execute("DELETE FROM client_rank_history WHERE client_id = ?", (cid,))
            conn.execute("DELETE FROM clients WHERE id = ?", (cid,))
        conn.commit()
    except sqlite3.IntegrityError as e:
        raised = str(e)
    assert raised is not None, "보고서가 있는데도 FK 오류가 나지 않았다 — 재현 실패(스키마 계약이 달라졌다)"
    assert "FOREIGN KEY" in raised.upper(), f"예상과 다른 오류: {raised}"


def test_new_order_deletes_client_and_reports():
    """고친 순서(reports 를 clients 앞에서 지운다)는 성공하고 업체·경쟁사·자식 전부 사라진다."""
    conn = _seed()
    for cid in _linked_del_ids(conn, 10):
        conn.execute("DELETE FROM client_analyses WHERE client_id = ?", (cid,))
        conn.execute("DELETE FROM client_rank_history WHERE client_id = ?", (cid,))
        conn.execute("DELETE FROM reports WHERE client_id = ?", (cid,))
        conn.execute("DELETE FROM clients WHERE id = ?", (cid,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM clients").fetchone()["c"] == 0, "업체·경쟁사가 남았다"
    assert conn.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"] == 0, "보고서 고아가 남았다"
    for t in ("client_analyses", "client_rank_history", "client_keyword_product"):
        assert conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] == 0, f"{t} 자식이 남았다"


def test_cascade_children_autodelete_but_reports_do_not():
    """세 자식은 CASCADE 라 clients 삭제만으로 사라지고, reports 는 cascade 가 없어 막는다.
    → 그래서 삭제 로직은 reports 만 명시적으로 지우면 충분하다(다른 셋은 이미 자동)."""
    conn = _seed()
    # 보고서를 먼저 비운 뒤 clients 만 지우면 — 세 자식은 CASCADE 로 자동 삭제된다.
    conn.execute("DELETE FROM reports WHERE client_id IN (10,11)")
    conn.execute("DELETE FROM clients WHERE id = 11")
    conn.execute("DELETE FROM clients WHERE id = 10")
    conn.commit()
    for t in ("client_analyses", "client_rank_history", "client_keyword_product"):
        assert conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] == 0, f"{t} 가 CASCADE 로 지워지지 않았다"

    # 반대로, reports 가 남아 있으면 clients 삭제가 막히는 것도 다시 확인.
    conn2 = _seed()
    blocked = False
    try:
        conn2.execute("DELETE FROM clients WHERE id = 11")  # 경쟁사엔 보고서가 있다
    except sqlite3.IntegrityError:
        blocked = True
    assert blocked, "보고서가 있는 업체 삭제가 막히지 않았다 — reports FK 계약이 사라졌다"


def test_source_delete_client_removes_reports():
    """실제 소스(client_dashboard.delete_client)가 reports 를 clients 앞에서 지우는지 확인한다.
    스키마 시험이 통과해도 실제 코드에서 그 줄이 빠지면 버그가 되살아나므로 함께 고정한다."""
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "client_dashboard.py"))
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    # delete_client 함수 본문만 잘라서 확인(다른 곳의 우연한 문자열에 속지 않도록).
    m = re.search(r"\ndef delete_client\(.*?(?=\n(?:def|@router)\b)", src, re.S)
    assert m, "delete_client 함수를 소스에서 찾지 못했다"
    body = m.group(0)
    del_reports = re.search(r"DELETE\s+FROM\s+reports\s+WHERE\s+client_id", body, re.I)
    del_clients = re.search(r"DELETE\s+FROM\s+clients\s+WHERE\s+id", body, re.I)
    assert del_reports, "delete_client 이 reports 를 지우지 않는다 — 신고 #259 재발 위험"
    assert del_clients, "delete_client 에서 clients 삭제 구문을 찾지 못했다"
    assert del_reports.start() < del_clients.start(), "reports 삭제가 clients 삭제보다 앞서야 한다(순서 역전)"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
