"""전산 담당자 변경이 호출하는 로직분석 운영 소유권 이관 모듈.

최초 작성자는 ``original_*`` 컬럼과 기존 분석/보고서의 ``created_by``에 보존하고,
현재 화면 권한에 쓰이는 광고주·추적 등록의 운영 소유권만 후임자에게 넘긴다.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


_SECRET_VALUE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|token|secret|authorization)"
    r"(\s*[=:]\s*)([^\s,;}&]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")


def sanitize_handover_error(message: object) -> str:
    """외부 오류가 원장·응답으로 갈 때 인증정보 모양을 제거한다."""
    text = str(message or "담당자 변경 처리 오류")[:1000]
    text = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[MASKED]", text)
    return _BEARER_VALUE.sub("Bearer [MASKED]", text)


@dataclass(frozen=True)
class HandoverTransferCommand:
    request_key: str
    client_id: int
    from_username: str
    to_username: str
    to_name: str
    place_business_keys: tuple[str, ...] = ()
    allow_inactive_target: bool = False


class HandoverTransferService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}

    def initialize(self) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_original_owner(conn, "clients", "original_created_by", "created_by")
            self._ensure_original_owner(conn, "tracked_products", "original_user_id", "user_id")
            self._ensure_original_owner(conn, "place_track_target", "original_created_by", "created_by")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS handover_owner_backup_20260828 (
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    owner_id INTEGER,
                    backed_up_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    PRIMARY KEY (entity_type, entity_id)
                );
                CREATE TABLE IF NOT EXISTS handover_transfer_request (
                    request_key TEXT PRIMARY KEY,
                    client_id INTEGER NOT NULL,
                    from_username TEXT NOT NULL,
                    to_username TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );
                """
            )
            self._backup_current_owners(conn, "clients", "created_by")
            self._backup_current_owners(conn, "tracked_products", "user_id")
            self._backup_current_owners(conn, "place_track_target", "created_by")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_original_owner(self, conn: sqlite3.Connection, table: str,
                               original_column: str, owner_column: str) -> None:
        if original_column not in self._columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {original_column} INTEGER")
        conn.execute(
            f"UPDATE {table} SET {original_column}={owner_column} "
            f"WHERE {original_column} IS NULL"
        )

    @staticmethod
    def _backup_current_owners(conn: sqlite3.Connection, table: str, owner_column: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO handover_owner_backup_20260828(entity_type, entity_id, owner_id) "
            f"SELECT ?, id, {owner_column} FROM {table}",
            (table,),
        )

    def transfer(self, command: HandoverTransferCommand) -> dict:
        self._validate_command(command)
        self.initialize()
        conn = self._connect()
        try:
            previous = conn.execute(
                "SELECT status, result_json FROM handover_transfer_request WHERE request_key=?",
                (command.request_key,),
            ).fetchone()
            if previous and previous["status"] == "SUCCESS":
                return json.loads(previous["result_json"])

            conn.execute("BEGIN IMMEDIATE")
            from_user = self._require_user(conn, command.from_username)
            to_user = self._resolve_successor(
                conn, command.to_username, command.to_name, command.allow_inactive_target
            )
            client = conn.execute(
                "SELECT id, name, created_by FROM clients WHERE id=?", (command.client_id,)
            ).fetchone()
            if client is None:
                raise ValueError("로직분석 광고주를 찾을 수 없습니다.")
            self._assert_owner(client["created_by"], from_user["id"], to_user["id"], "광고주")

            product_ids = [int(row[0]) for row in conn.execute(
                "SELECT tracked_product_id FROM rank_link WHERE client_id=? ORDER BY tracked_product_id",
                (command.client_id,),
            )]
            place_ids = self._resolve_place_target_ids(conn, command.place_business_keys)
            self._assert_rows_owned(conn, "tracked_products", "user_id", product_ids,
                                    from_user["id"], to_user["id"], "쇼핑 순위추적")
            self._assert_rows_owned(conn, "place_track_target", "created_by", place_ids,
                                    from_user["id"], to_user["id"], "플레이스 순위추적")

            moved_clients = conn.execute(
                "UPDATE clients SET created_by=?, updated_at=datetime('now','localtime') "
                "WHERE id=? AND created_by=?",
                (to_user["id"], command.client_id, from_user["id"]),
            ).rowcount
            moved_products = self._move_rows(conn, "tracked_products", "user_id", product_ids,
                                             from_user["id"], to_user["id"])
            moved_places = self._move_rows(conn, "place_track_target", "created_by", place_ids,
                                           from_user["id"], to_user["id"])

            verified = self._verify(conn, command.client_id, product_ids, place_ids, to_user["id"])
            result = {
                "success": True,
                "request_key": command.request_key,
                "client_id": command.client_id,
                "moved": {
                    "clients": moved_clients,
                    "tracked_products": moved_products,
                    "place_targets": moved_places,
                },
                "verified": verified,
            }
            conn.execute(
                "INSERT INTO handover_transfer_request(request_key, client_id, from_username, to_username, status, result_json) "
                "VALUES (?, ?, ?, ?, 'SUCCESS', ?) "
                "ON CONFLICT(request_key) DO UPDATE SET status='SUCCESS', result_json=excluded.result_json, "
                "updated_at=datetime('now','localtime')",
                (command.request_key, command.client_id, command.from_username,
                 command.to_username, json.dumps(result, ensure_ascii=False)),
            )
            conn.commit()
            return result
        except Exception as exc:
            conn.rollback()
            self._record_failure(command, str(exc))
            raise
        finally:
            conn.close()

    def preview(self, command: HandoverTransferCommand) -> dict:
        """실제 변경 없이 안정 연결 자산과 현재 담당자 일치 여부를 검사한다."""
        self._validate_command(command)
        self.initialize()
        conn = self._connect()
        try:
            from_user = self._require_user(conn, command.from_username)
            to_user = conn.execute(
                "SELECT id, username, is_active FROM users WHERE username=?",
                (command.to_username,),
            ).fetchone()
            client = conn.execute(
                "SELECT id, created_by FROM clients WHERE id=?", (command.client_id,)
            ).fetchone()
            if client is None:
                raise ValueError("로직분석 광고주를 찾을 수 없습니다.")
            allowed_to_id = int(to_user["id"]) if to_user is not None else -1
            self._assert_owner(
                int(client["created_by"]), int(from_user["id"]), allowed_to_id, "광고주"
            )
            product_ids = [int(row[0]) for row in conn.execute(
                "SELECT tracked_product_id FROM rank_link WHERE client_id=? ORDER BY tracked_product_id",
                (command.client_id,),
            )]
            place_ids = self._resolve_place_target_ids(conn, command.place_business_keys)
            self._assert_rows_owned(
                conn, "tracked_products", "user_id", product_ids,
                int(from_user["id"]), allowed_to_id, "쇼핑 순위추적",
            )
            self._assert_rows_owned(
                conn, "place_track_target", "created_by", place_ids,
                int(from_user["id"]), allowed_to_id, "플레이스 순위추적",
            )
            return {
                "ready": True,
                "client_id": command.client_id,
                "successor_account_exists": to_user is not None,
                "asset_counts": {
                    "clients": 1,
                    "tracked_products": len(product_ids),
                    "place_targets": len(place_ids),
                },
                "asset_ids": {
                    "clients": [str(command.client_id)],
                    "tracked_products": [str(value) for value in product_ids],
                    "place_targets": [str(value) for value in place_ids],
                },
            }
        finally:
            conn.close()

    def request_status(self, request_key: str) -> dict:
        self.initialize()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT request_key, client_id, from_username, to_username, status, result_json, "
                "created_at, updated_at FROM handover_transfer_request WHERE request_key=?",
                (request_key,),
            ).fetchone()
            if row is None:
                raise ValueError("이관 요청 이력을 찾을 수 없습니다.")
            result = json.loads(row["result_json"] or "{}")
            return {
                "request_key": row["request_key"],
                "client_id": row["client_id"],
                "from_username": row["from_username"],
                "to_username": row["to_username"],
                "status": row["status"],
                "result": result,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def residual(self, username: str) -> dict:
        self.initialize()
        conn = self._connect()
        try:
            user = self._require_user(conn, username)
            counts = {
                "clients": conn.execute("SELECT COUNT(*) FROM clients WHERE created_by=?", (user["id"],)).fetchone()[0],
                "tracked_products": conn.execute("SELECT COUNT(*) FROM tracked_products WHERE user_id=?", (user["id"],)).fetchone()[0],
                "place_targets": conn.execute("SELECT COUNT(*) FROM place_track_target WHERE created_by=?", (user["id"],)).fetchone()[0],
            }
            return {"username": username, "counts": counts, "total": sum(counts.values())}
        finally:
            conn.close()

    @staticmethod
    def _validate_command(command: HandoverTransferCommand) -> None:
        if not command.request_key.strip() or len(command.request_key) > 160:
            raise ValueError("요청 고유키가 필요합니다.")
        if command.client_id <= 0:
            raise ValueError("로직분석 광고주 ID가 필요합니다.")
        if not command.from_username.strip() or not command.to_username.strip():
            raise ValueError("기존·후임 사용자 식별값이 필요합니다.")
        if command.from_username == command.to_username:
            raise ValueError("같은 사용자에게 이관할 수 없습니다.")

    @staticmethod
    def _require_user(conn: sqlite3.Connection, username: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT id, username, is_active FROM users WHERE username=?", (username,)
        ).fetchone()
        if row is None:
            raise ValueError(f"로직분석 사용자({username})를 찾을 수 없습니다.")
        return row

    @staticmethod
    def _resolve_successor(conn: sqlite3.Connection, username: str, name: str,
                           allow_inactive: bool = False) -> sqlite3.Row:
        row = conn.execute(
            "SELECT id, username, is_active FROM users WHERE username=?", (username,)
        ).fetchone()
        if row is None:
            import bcrypt

            now = datetime.now().isoformat()
            password_hash = bcrypt.hashpw(
                secrets.token_urlsafe(48).encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            conn.execute(
                "INSERT INTO users(username, password_hash, name, role, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, 'manager', 1, ?, ?)",
                (username, password_hash, (name or username)[:100], now, now),
            )
            row = conn.execute(
                "SELECT id, username, is_active FROM users WHERE username=?", (username,)
            ).fetchone()
        if not bool(row["is_active"]) and not allow_inactive:
            raise ValueError("후임자 로직분석 계정이 비활성 상태입니다.")
        return row

    def deactivate(self, username: str) -> dict:
        """전체 이관 검증 뒤 퇴사자의 Logic 로그인을 멱등 차단한다."""
        self.initialize()
        conn = self._connect()
        try:
            row = conn.execute("SELECT id, is_active FROM users WHERE username=?", (username,)).fetchone()
            if row is None:
                return {"success": True, "deactivated": False}
            changed = conn.execute(
                "UPDATE users SET is_active=0, updated_at=datetime('now','localtime') "
                "WHERE username=? AND is_active<>0", (username,)
            ).rowcount
            conn.commit()
            return {"success": True, "deactivated": bool(changed)}
        finally:
            conn.close()

    @staticmethod
    def _assert_owner(current_owner: int, from_id: int, to_id: int, label: str) -> None:
        if current_owner not in (from_id, to_id):
            raise ValueError(f"{label}의 현재 담당자가 퇴사자와 일치하지 않습니다.")

    @classmethod
    def _assert_rows_owned(cls, conn: sqlite3.Connection, table: str, owner_column: str,
                           ids: Iterable[int], from_id: int, to_id: int, label: str) -> None:
        for row_id in ids:
            row = conn.execute(
                f"SELECT {owner_column} FROM {table} WHERE id=?", (row_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"{label} 자료를 찾을 수 없습니다: {row_id}")
            cls._assert_owner(row[0], from_id, to_id, label)

    @staticmethod
    def _move_rows(conn: sqlite3.Connection, table: str, owner_column: str,
                   ids: Iterable[int], from_id: int, to_id: int) -> int:
        moved = 0
        for row_id in ids:
            moved += conn.execute(
                f"UPDATE {table} SET {owner_column}=? WHERE id=? AND {owner_column}=?",
                (to_id, row_id, from_id),
            ).rowcount
        return moved

    @staticmethod
    def _normal(value: str) -> str:
        return "".join(str(value or "").split()).lower()

    def _resolve_place_target_ids(self, conn: sqlite3.Connection,
                                  business_keys: Iterable[str]) -> list[int]:
        rows = conn.execute(
            "SELECT id, business_name, region, place_id FROM place_track_target"
        ).fetchall()
        resolved: list[int] = []
        for raw_key in business_keys:
            key = str(raw_key or "").strip()
            matches: list[int] = []
            if key.startswith("doc:"):
                place_id = key[4:].strip()
                matches = [int(row["id"]) for row in rows if str(row["place_id"] or "").strip() == place_id]
            elif key.startswith("nm:"):
                body = key[3:]
                name, _, region = body.partition("|")
                matches = [int(row["id"]) for row in rows
                           if self._normal(row["business_name"]) == self._normal(name)
                           and (not region or self._normal(row["region"]) == self._normal(region))]
            if not matches:
                raise ValueError("플레이스 연결 자료를 찾을 수 없습니다.")
            resolved.extend(matches)
        return sorted(set(resolved))

    @staticmethod
    def _verify(conn: sqlite3.Connection, client_id: int, product_ids: Iterable[int],
                place_ids: Iterable[int], to_id: int) -> bool:
        owner = conn.execute("SELECT created_by FROM clients WHERE id=?", (client_id,)).fetchone()
        if owner is None or owner[0] != to_id:
            return False
        for table, column, ids in (
            ("tracked_products", "user_id", product_ids),
            ("place_track_target", "created_by", place_ids),
        ):
            for row_id in ids:
                row = conn.execute(f"SELECT {column} FROM {table} WHERE id=?", (row_id,)).fetchone()
                if row is None or row[0] != to_id:
                    return False
        return True

    def _record_failure(self, command: HandoverTransferCommand, message: str) -> None:
        conn = self._connect()
        try:
            result = {"success": False, "message": sanitize_handover_error(message)[:500]}
            conn.execute(
                "INSERT INTO handover_transfer_request(request_key, client_id, from_username, to_username, status, result_json) "
                "VALUES (?, ?, ?, ?, 'FAILED', ?) "
                "ON CONFLICT(request_key) DO UPDATE SET status='FAILED', result_json=excluded.result_json, "
                "updated_at=datetime('now','localtime')",
                (command.request_key, command.client_id, command.from_username,
                 command.to_username, json.dumps(result, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()
