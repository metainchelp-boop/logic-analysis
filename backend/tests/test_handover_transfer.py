import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from handover_transfer import HandoverTransferCommand, HandoverTransferService


def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            role TEXT,
            is_active INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            updated_at TEXT
        );
        CREATE TABLE tracked_products (
            id INTEGER PRIMARY KEY,
            product_url TEXT,
            user_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE rank_link (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            tracked_product_id INTEGER NOT NULL
        );
        CREATE TABLE place_track_target (
            id INTEGER PRIMARY KEY,
            business_name TEXT,
            region TEXT,
            place_id TEXT,
            keyword TEXT,
            created_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE client_analyses (
            id INTEGER PRIMARY KEY,
            client_id INTEGER,
            created_by INTEGER,
            payload TEXT
        );
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY,
            client_id INTEGER,
            created_by INTEGER,
            title TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, ?, ?, 'manager', 1, '2026-01-01', '2026-01-01')",
        [
            (10, "leaver", "hash", "퇴사자"),
            (20, "successor", "hash", "후임자"),
        ],
    )
    conn.execute("INSERT INTO clients VALUES (100, '테스트 광고주', 10, 'active', '2026-01-01')")
    conn.execute("INSERT INTO tracked_products VALUES (200, 'https://example/200', 10, '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO rank_link VALUES (1, 100, 200)")
    conn.execute("INSERT INTO place_track_target VALUES (300, '테스트 광고주', '서울', '777', '테스트 키워드', 10, '2026-01-01')")
    conn.execute("INSERT INTO client_analyses VALUES (400, 100, 10, '{}')")
    conn.execute("INSERT INTO reports VALUES (500, 100, 10, '기존 보고서')")
    conn.commit()
    conn.close()


def test_transfer_moves_operational_ownership_and_preserves_historical_authors(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    service = HandoverTransferService(db_path)
    service.initialize()

    result = service.transfer(
        HandoverTransferCommand(
            request_key="handover-1-client-100",
            client_id=100,
            from_username="leaver",
            to_username="successor",
            to_name="후임자",
            place_business_keys=("doc:777",),
        )
    )

    assert result["success"] is True
    assert result["moved"] == {"clients": 1, "tracked_products": 1, "place_targets": 1}
    assert result["verified"] is True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT created_by FROM clients WHERE id=100").fetchone()[0] == 20
    assert conn.execute("SELECT original_created_by FROM clients WHERE id=100").fetchone()[0] == 10
    assert conn.execute("SELECT user_id FROM tracked_products WHERE id=200").fetchone()[0] == 20
    assert conn.execute("SELECT original_user_id FROM tracked_products WHERE id=200").fetchone()[0] == 10
    assert conn.execute("SELECT created_by FROM place_track_target WHERE id=300").fetchone()[0] == 20
    assert conn.execute("SELECT original_created_by FROM place_track_target WHERE id=300").fetchone()[0] == 10
    assert conn.execute("SELECT created_by FROM client_analyses WHERE id=400").fetchone()[0] == 10
    assert conn.execute("SELECT created_by FROM reports WHERE id=500").fetchone()[0] == 10
    conn.close()


def test_transfer_is_idempotent_for_the_same_request_key(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    service = HandoverTransferService(db_path)
    command = HandoverTransferCommand(
        request_key="handover-1-client-100",
        client_id=100,
        from_username="leaver",
        to_username="successor",
        to_name="후임자",
        place_business_keys=("doc:777",),
    )

    first = service.transfer(command)
    second = service.transfer(command)

    assert second == first
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT COUNT(*) FROM handover_transfer_request WHERE request_key=?",
        (command.request_key,),
    ).fetchone()[0] == 1
    assert conn.execute("SELECT original_created_by FROM clients WHERE id=100").fetchone()[0] == 10
    conn.close()


def test_residual_reports_unlinked_operational_assets(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO tracked_products VALUES (201, 'https://example/201', 10, '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    service = HandoverTransferService(db_path)

    service.transfer(
        HandoverTransferCommand(
            request_key="handover-1-client-100",
            client_id=100,
            from_username="leaver",
            to_username="successor",
            to_name="후임자",
            place_business_keys=("doc:777",),
        )
    )

    residual = service.residual("leaver")
    assert residual["counts"] == {"clients": 0, "tracked_products": 1, "place_targets": 0}
    assert residual["total"] == 1


def test_transfer_auto_provisions_successor_for_sso(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM users WHERE username='successor'")
    conn.commit()
    conn.close()
    service = HandoverTransferService(db_path)

    service.transfer(
        HandoverTransferCommand(
            request_key="handover-1-client-100",
            client_id=100,
            from_username="leaver",
            to_username="successor",
            to_name="후임자",
            place_business_keys=("doc:777",),
        )
    )

    conn = sqlite3.connect(db_path)
    created = conn.execute(
        "SELECT name, role, is_active FROM users WHERE username='successor'"
    ).fetchone()
    assert created == ("후임자", "manager", 1)
    conn.close()


def test_invalid_place_connection_rolls_back_all_owner_changes(tmp_path):
    db_path = str(tmp_path / "logic.db")
    _db(db_path)
    service = HandoverTransferService(db_path)

    try:
        service.transfer(
            HandoverTransferCommand(
                request_key="handover-1-client-100",
                client_id=100,
                from_username="leaver",
                to_username="successor",
                to_name="후임자",
                place_business_keys=("doc:missing",),
            )
        )
        assert False, "없는 플레이스 연결은 실패해야 합니다."
    except ValueError as exc:
        assert "플레이스 연결 자료" in str(exc)

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT created_by FROM clients WHERE id=100").fetchone()[0] == 10
    assert conn.execute("SELECT user_id FROM tracked_products WHERE id=200").fetchone()[0] == 10
    assert conn.execute("SELECT status FROM handover_transfer_request").fetchone()[0] == "FAILED"
    conn.close()
