import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from report_access import can_manage_report, managed_report_predicate


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE clients (id INTEGER PRIMARY KEY, created_by INTEGER NOT NULL);
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            title TEXT
        );
        INSERT INTO clients VALUES (100, 20);
        INSERT INTO reports VALUES (500, 100, 10, '퇴사자가 만든 보고서');
        """
    )
    return conn


def test_successor_can_manage_historical_report_without_changing_author():
    conn = _connection()

    assert can_manage_report(conn, 500, 20) is True
    assert conn.execute("SELECT created_by FROM reports WHERE id=500").fetchone()[0] == 10


def test_unrelated_user_cannot_manage_report_and_list_predicate_matches_owner():
    conn = _connection()
    predicate = managed_report_predicate("r")

    assert can_manage_report(conn, 500, 30) is False
    rows = conn.execute(
        f"SELECT r.id FROM reports r WHERE {predicate}", (20, 20)
    ).fetchall()
    assert rows == [(500,)]
