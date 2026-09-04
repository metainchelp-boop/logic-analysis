"""신고 #256 — 보고서 담당자 정렬(②) 검증. 네트워크 없이 결정적으로 실행.

실행:  python tests/test_report_owner_sync.py   (또는 pytest tests/)
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import report_owner_sync as ros


# ── 순수 판정 로직 ────────────────────────────────────────────────

def test_plan_aligns_only_when_different():
    items = [
        {"logic_client_id": "1", "manager_login": "kimwoori", "manager_name": "김우리"},   # 소유 다름 → 변경
        {"logic_client_id": "2", "manager_login": "leejinhee", "manager_name": "이진희"},  # 이미 맞음
        {"logic_client_id": "3", "manager_login": "", "manager_name": ""},                 # 미배정
        {"logic_client_id": "999", "manager_login": "kimwoori", "manager_name": "김우리"}, # 업체 없음
        {"logic_client_id": "4", "manager_login": "newbie", "manager_name": "새담당"},     # 계정 없음
    ]
    clients_owner = {1: 50, 2: 60, 4: 70}          # 존재하는 업체와 현재 소유
    users_by_login = {"kimwoori": 60, "leejinhee": 60}  # 계정 있는 사용자

    plan = ros.plan_owner_changes(items, clients_owner, users_by_login)

    assert plan.aligned_already == 1        # client 2
    assert plan.unassigned == 1             # client 3
    assert plan.unknown_client == 1         # client 999
    by_cid = {c.client_id: c for c in plan.changes}
    assert set(by_cid) == {1, 4}
    assert by_cid[1].to_user_id == 60 and by_cid[1].from_owner == 50
    assert by_cid[4].to_user_id is None     # 계정 없음 → 적용 시 생성
    print("OK test_plan_aligns_only_when_different")


def test_plan_ignores_bad_client_id():
    items = [{"logic_client_id": None, "manager_login": "x", "manager_name": "x"},
             {"logic_client_id": "notanint", "manager_login": "x", "manager_name": "x"}]
    plan = ros.plan_owner_changes(items, {1: 1}, {"x": 1})
    assert plan.unknown_client == 2 and not plan.changes
    print("OK test_plan_ignores_bad_client_id")


# ── 엔드투엔드(임시 DB) ───────────────────────────────────────────

def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, name TEXT, role TEXT, is_active INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_by INTEGER NOT NULL,
            status TEXT DEFAULT 'active', updated_at TEXT
        );
        CREATE TABLE tracked_products (id INTEGER PRIMARY KEY, user_id INTEGER);
        CREATE TABLE place_track_target (id INTEGER PRIMARY KEY, created_by INTEGER);
        CREATE TABLE reports (id INTEGER PRIMARY KEY, client_id INTEGER, created_by INTEGER, title TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO users(id, username, password_hash, name, role, is_active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,1,'now','now')",
        [(50, "gangsinuk", "h", "강신욱", "manager"),
         (60, "leejinhee", "h", "이진희", "manager"),
         (70, "kimwoori", "h", "김우리", "manager")],
    )
    # client 1: 강신욱(50) 소유인데 전산 담당자는 김우리(70) → 옮겨야 함
    # client 2: 이미 이진희(60) — 그대로
    conn.executemany(
        "INSERT INTO clients(id, name, created_by) VALUES (?,?,?)",
        [(1, "업체A", 50), (2, "업체B", 60)],
    )
    # 보고서 작성자는 원저자 — 절대 바뀌면 안 됨
    conn.executemany(
        "INSERT INTO reports(id, client_id, created_by, title) VALUES (?,?,?,?)",
        [(11, 1, 50, "업체A 보고서"), (12, 2, 60, "업체B 보고서")],
    )
    conn.commit()
    conn.close()


def _run(tmp, items, dry_run=False):
    ros.fetch_client_managers = lambda base, api_key, timeout=15: items  # 네트워크 대체
    return ros.run_report_owner_sync(db_path=tmp, base="http://x", api_key="k",
                                     dry_run=dry_run, run_id="testrun")


def test_end_to_end_realign_and_preserve(tmp_path=None):
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), "t.db")
    _db(tmp)
    items = [
        {"logic_client_id": "1", "manager_login": "kimwoori", "manager_name": "김우리"},
        {"logic_client_id": "2", "manager_login": "leejinhee", "manager_name": "이진희"},
    ]

    # 1) 미리보기는 아무것도 바꾸지 않는다
    prev = _run(tmp, items, dry_run=True)
    assert prev["ok"] and prev["would_change"] == 1 and prev["aligned_already"] == 1
    conn = sqlite3.connect(tmp)
    assert conn.execute("SELECT created_by FROM clients WHERE id=1").fetchone()[0] == 50
    conn.close()

    # 2) 실제 실행 — 업체A 소유가 김우리(70)로, 업체B는 그대로
    res = _run(tmp, items)
    assert res["ok"] and res["changed"] == 1 and res["aligned_already"] == 1
    conn = sqlite3.connect(tmp)
    assert conn.execute("SELECT created_by FROM clients WHERE id=1").fetchone()[0] == 70
    assert conn.execute("SELECT created_by FROM clients WHERE id=2").fetchone()[0] == 60
    # 작성자 이력은 불변 (보고서·original_created_by)
    assert conn.execute("SELECT created_by FROM reports WHERE id=11").fetchone()[0] == 50
    assert conn.execute("SELECT original_created_by FROM clients WHERE id=1").fetchone()[0] == 50
    # 되돌릴 근거 로그
    row = conn.execute("SELECT from_owner, to_owner, manager_login FROM report_owner_sync_log WHERE client_id=1").fetchone()
    assert row == (50, 70, "kimwoori")
    conn.close()

    # 3) 멱등 — 다시 돌리면 0건
    res2 = _run(tmp, items)
    assert res2["ok"] and res2["changed"] == 0 and res2["aligned_already"] == 2
    print("OK test_end_to_end_realign_and_preserve")


def test_creates_missing_account(tmp_path=None):
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), "t.db")
    _db(tmp)
    # 전산 담당자가 로직분석 계정이 아직 없는 사람(newmgr) — 적용 시 생성 후 소유 이관
    items = [{"logic_client_id": "1", "manager_login": "newmgr", "manager_name": "새관리자"}]
    res = _run(tmp, items)
    assert res["ok"] and res["changed"] == 1 and res["created_accounts"] == 1
    conn = sqlite3.connect(tmp)
    uid = conn.execute("SELECT id FROM users WHERE username='newmgr'").fetchone()[0]
    assert conn.execute("SELECT created_by FROM clients WHERE id=1").fetchone()[0] == uid
    assert conn.execute("SELECT role FROM users WHERE username='newmgr'").fetchone()[0] == "manager"
    conn.close()
    print("OK test_creates_missing_account")


def test_no_key_is_noop():
    res = ros.run_report_owner_sync(db_path=":memory:", base="http://x", api_key="")
    assert res["ok"] is False
    print("OK test_no_key_is_noop")


if __name__ == "__main__":
    test_plan_aligns_only_when_different()
    test_plan_ignores_bad_client_id()
    test_end_to_end_realign_and_preserve()
    test_creates_missing_account()
    test_no_key_is_noop()
    print("ALL PASS")
