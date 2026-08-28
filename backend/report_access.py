"""보고서 작성 이력과 현재 광고주 운영 권한을 분리하는 접근 규칙."""

from __future__ import annotations

import sqlite3


def managed_report_predicate(report_alias: str = "r") -> str:
    """작성자 또는 현재 광고주 운영 담당자가 보고서를 관리할 수 있다."""
    if not report_alias.replace("_", "").isalnum():
        raise ValueError("안전하지 않은 보고서 별칭입니다.")
    return (
        f"({report_alias}.created_by = ? OR EXISTS ("
        "SELECT 1 FROM clients c "
        f"WHERE c.id = {report_alias}.client_id AND c.created_by = ?))"
    )


def can_manage_report(conn: sqlite3.Connection, report_id: int, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM reports r WHERE r.id = ? AND "
        + managed_report_predicate("r"),
        (report_id, user_id, user_id),
    ).fetchone()
    return row is not None
