"""Java BE 클라이언트와 실제 Logic API 경계를 검증하는 일회성 가짜자료 서버."""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn
from fastapi import FastAPI, Header, HTTPException

from handover_transfer import HandoverTransferService
from handover_transfer_api import create_handover_router
from report_access import can_manage_report


DB_PATH = os.environ["HANDOVER_FIXTURE_DB"]
SERVICE_KEY = os.environ["HANDOVER_FIXTURE_KEY"]


def seed() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, name TEXT, role TEXT, is_active INTEGER,
          created_at TEXT, updated_at TEXT);
        CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
          created_by INTEGER NOT NULL, status TEXT DEFAULT 'active', updated_at TEXT);
        CREATE TABLE tracked_products (id INTEGER PRIMARY KEY, product_url TEXT,
          user_id INTEGER, created_at TEXT, updated_at TEXT);
        CREATE TABLE rank_link (id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL,
          tracked_product_id INTEGER NOT NULL);
        CREATE TABLE place_track_target (id INTEGER PRIMARY KEY, business_name TEXT,
          region TEXT, place_id TEXT, keyword TEXT, created_by INTEGER, created_at TEXT);
        CREATE TABLE client_analyses (id INTEGER PRIMARY KEY, client_id INTEGER,
          created_by INTEGER, payload TEXT);
        CREATE TABLE reports (id INTEGER PRIMARY KEY, client_id INTEGER,
          created_by INTEGER, title TEXT);
        """
    )
    users = [(10, "leaver", "퇴사자"), (20, "successor", "후임자1"),
             (21, "successor2", "후임자2"), (22, "successor3", "후임자3")]
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, 'hash', ?, 'manager', 1, '2026-01-01', '2026-01-01')",
        users,
    )
    for offset in range(6):
        client_id = 100 + offset
        conn.execute("INSERT INTO clients VALUES (?, ?, 10, 'active', '2026-01-01')",
                     (client_id, f"통합검증 광고주{offset + 1}"))
        conn.execute("INSERT INTO tracked_products VALUES (?, ?, 10, '2026-01-01', '2026-01-01')",
                     (200 + offset, f"https://example/{200 + offset}"))
        conn.execute("INSERT INTO rank_link VALUES (?, ?, ?)", (offset + 1, client_id, 200 + offset))
        conn.execute("INSERT INTO place_track_target VALUES (?, ?, '서울', ?, '검증', 10, '2026-01-01')",
                     (300 + offset, f"통합검증 광고주{offset + 1}", str(777 + offset)))
        conn.execute("INSERT INTO client_analyses VALUES (?, ?, 10, '{}')", (400 + offset, client_id))
        conn.execute("INSERT INTO reports VALUES (?, ?, 10, ?)",
                     (500 + offset, client_id, f"과거 보고서{offset + 1}"))
    conn.commit()
    conn.close()


def require_key(value: str | None) -> None:
    if value != SERVICE_KEY:
        raise HTTPException(status_code=401, detail="fixture key mismatch")


class FixtureHandoverTransferService(HandoverTransferService):
    """실제 연결·소유권 로직은 유지하고 지정 광고주 전송만 한 번 실패시키는 테스트 훅."""

    def __init__(self, db_path: str):
        super().__init__(db_path)
        self.fail_once: set[int] = set()

    def transfer(self, command):
        if command.client_id in self.fail_once:
            self.fail_once.remove(command.client_id)
            raise ValueError("통합검증용 일시 장애")
        return super().transfer(command)


seed()
service = FixtureHandoverTransferService(DB_PATH)
service.initialize()
app = FastAPI()
app.include_router(create_handover_router(service, SERVICE_KEY))


@app.get("/__fixture/state")
def state(x_handover_key: str | None = Header(default=None)):
    require_key(x_handover_key)
    conn = sqlite3.connect(DB_PATH)
    try:
        client_owners = dict(conn.execute("SELECT id, created_by FROM clients ORDER BY id").fetchall())
        report_authors = dict(conn.execute("SELECT client_id, created_by FROM reports ORDER BY client_id").fetchall())
        analysis_authors = dict(conn.execute("SELECT client_id, created_by FROM client_analyses WHERE id < 600 ORDER BY client_id").fetchall())
        access = {
            str(client_id): {
                "formerAuthor": can_manage_report(conn, 500 + (client_id - 100), 10),
                "currentOwner": can_manage_report(conn, 500 + (client_id - 100), owner_id),
            }
            for client_id, owner_id in client_owners.items()
        }
        requests = dict(conn.execute(
            "SELECT client_id, COUNT(*) FROM handover_transfer_request GROUP BY client_id ORDER BY client_id"
        ).fetchall())
        user_active = dict(conn.execute("SELECT username, is_active FROM users ORDER BY id").fetchall())
        return {"clientOwners": client_owners, "reportAuthors": report_authors,
                "analysisAuthors": analysis_authors, "reportAccess": access,
                "requestCounts": requests, "userActive": user_active}
    finally:
        conn.close()


@app.post("/__fixture/follow-up/{client_id}/{username}")
def follow_up(client_id: int, username: str, x_handover_key: str | None = Header(default=None)):
    require_key(x_handover_key)
    conn = sqlite3.connect(DB_PATH)
    try:
        user = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        owner = conn.execute("SELECT created_by FROM clients WHERE id=?", (client_id,)).fetchone()
        if user is None or owner is None or user[0] != owner[0]:
            raise HTTPException(status_code=403, detail="current owner only")
        conn.execute("INSERT INTO client_analyses(client_id, created_by, payload) VALUES (?, ?, ?)",
                     (client_id, user[0], '{"source":"handover-integration"}'))
        conn.commit()
        return {"created": True, "createdBy": user[0]}
    finally:
        conn.close()


@app.post("/__fixture/fail-once/{client_id}")
def fail_once(client_id: int, x_handover_key: str | None = Header(default=None)):
    require_key(x_handover_key)
    service.fail_once.add(client_id)
    return {"armed": True, "clientId": client_id}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["HANDOVER_FIXTURE_PORT"]), log_level="warning")
