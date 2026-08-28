import os
import sqlite3
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from handover_transfer import HandoverTransferService
from handover_transfer_api import create_handover_router


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
        CREATE TABLE tracked_products (
            id INTEGER PRIMARY KEY, product_url TEXT, user_id INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE rank_link (
            id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL,
            tracked_product_id INTEGER NOT NULL
        );
        CREATE TABLE place_track_target (
            id INTEGER PRIMARY KEY, business_name TEXT, region TEXT, place_id TEXT,
            keyword TEXT, created_by INTEGER, created_at TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, 'hash', ?, 'manager', 1, '2026-01-01', '2026-01-01')",
        [(10, "leaver", "퇴사자"), (20, "successor", "후임자")],
    )
    conn.execute("INSERT INTO clients VALUES (100, '테스트 광고주', 10, 'active', '2026-01-01')")
    conn.execute("INSERT INTO tracked_products VALUES (200, 'https://example/200', 10, '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO rank_link VALUES (1, 100, 200)")
    conn.execute("INSERT INTO place_track_target VALUES (300, '테스트 광고주', '서울', '777', '키워드', 10, '2026-01-01')")
    conn.commit()
    conn.close()


def _client(db_path):
    app = FastAPI()
    app.include_router(
        create_handover_router(HandoverTransferService(db_path), "internal-secret")
    )
    return TestClient(app)


def _payload():
    return {
        "requestKey": "handover-1-client-100",
        "clientId": 100,
        "fromUsername": "leaver",
        "toUsername": "successor",
        "toName": "후임자",
        "placeBusinessKeys": ["doc:777"],
    }


def test_internal_transfer_api_requires_service_key(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    client = _client(db_path)

    response = client.post("/api/internal/handovers/transfer", json=_payload())

    assert response.status_code == 401
    assert response.json() == {"detail": "서비스 인증에 실패했습니다."}


def test_internal_preview_transfer_status_and_residual_contract(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    client = _client(db_path)
    headers = {"X-Handover-Key": "internal-secret"}

    preview = client.post("/api/internal/handovers/preview", json=_payload(), headers=headers)
    transfer = client.post("/api/internal/handovers/transfer", json=_payload(), headers=headers)
    status = client.get(
        "/api/internal/handovers/requests/handover-1-client-100", headers=headers
    )
    residual = client.get("/api/internal/handovers/residual/leaver", headers=headers)

    assert preview.status_code == 200
    assert preview.json()["assetCounts"] == {
        "clients": 1,
        "trackedProducts": 1,
        "placeTargets": 1,
    }
    assert transfer.status_code == 200
    assert transfer.json()["verified"] is True
    assert status.json()["status"] == "SUCCESS"
    assert residual.json()["total"] == 0
    response_text = " ".join(
        [preview.text, transfer.text, status.text, residual.text]
    ).lower()
    assert "password" not in response_text
    assert "internal-secret" not in response_text

