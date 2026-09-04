"""전산 현재 담당자에 맞춰 보고서 소유(clients.created_by)를 매일 자가 정렬한다 (신고 #256).

배경 — 로직분석 보고서는 `clients.created_by`(현재 담당자)로만 열람 권한을 준다(report_access).
작성자(reports.created_by)는 이력으로만 남는다. 전산에서 담당자가 바뀌어도(가망 수정 페이지)
그 신호가 로직분석까지 오지 않아 옛 담당자에게 보고서가 묶여 있었다(퇴사자 인수인계 최종 확정만
소유를 옮기는데 그 흐름은 거의 안 돈다). 이 배치가 전산의 현재 담당자를 매일 읽어 소유를 맞춘다.

원리 — 전산 ① `GET /api/report-sync/client-managers` 가 연결된 LOGIC_CLIENT 원천마다
`{logic_client_id(=clients.id), manager_login(=users.username), manager_name}` 을 준다.
그 담당자 로그인을 로직분석 users.id 로 찾아, 다른 사람 소유면 `clients.created_by` 를 맞춘다.

안전장치 —
- **덧붙이기만**: 작성자 이력(reports.created_by)·original_created_by 는 건드리지 않는다.
- **되돌릴 근거**: 변경 전 소유는 handover_owner_backup_20260828(멱등 baseline)에 남고,
  이번 변경은 전건 report_owner_sync_log(from→to·run_id)에 기록한다. 그 표로 되돌릴 수 있다.
- **멱등**: 이미 맞으면 건드리지 않는다. 매일 돌아도 첫 실행만 크게 바뀌고 이후엔 자가 유지.
- **키·조회 실패 시 무동작**(안전 기본값). 담당자 없음(null)·업체 없음은 세고 건너뛴다.
- **미리보기(dry_run)**: 실제 변경 없이 몇 건이 바뀔지만 센다(배포 전 규모 확인용).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field

import requests

from handover_transfer import HandoverTransferService


@dataclass
class OwnerChange:
    client_id: int
    from_owner: int
    to_login: str
    to_name: str
    to_user_id: int | None  # None = 로직분석 계정이 아직 없음(적용 시 생성)


@dataclass
class SyncPlan:
    changes: list[OwnerChange] = field(default_factory=list)
    aligned_already: int = 0     # 이미 맞아서 건드릴 것 없음
    unassigned: int = 0          # 전산 담당자 미배정(manager_login 없음)
    unknown_client: int = 0      # 그 id 의 로직분석 업체가 없음


def plan_owner_changes(items, clients_owner, users_by_login):
    """순수 판정(단위테스트 대상): 전산 응답 + 현재 소유/사용자 맵 → 바꿀 목록·통계.

    items: [{logic_client_id, manager_login, manager_name}, ...]
    clients_owner: {client_id(int): created_by(int)} — 존재하는 로직분석 업체만.
    users_by_login: {username(str): user_id(int)} — 이미 있는 로직분석 계정만.
    """
    plan = SyncPlan()
    for it in items:
        login = (it.get("manager_login") or "").strip()
        if not login:
            plan.unassigned += 1
            continue
        try:
            cid = int(it.get("logic_client_id"))
        except (TypeError, ValueError):
            plan.unknown_client += 1
            continue
        if cid not in clients_owner:
            plan.unknown_client += 1
            continue
        target_id = users_by_login.get(login)  # None 이면 계정 없음 → 적용 시 생성
        current = clients_owner[cid]
        if target_id is not None and current == target_id:
            plan.aligned_already += 1
            continue
        plan.changes.append(OwnerChange(
            client_id=cid,
            from_owner=int(current) if current is not None else 0,
            to_login=login,
            to_name=(it.get("manager_name") or login),
            to_user_id=target_id,
        ))
    return plan


def fetch_client_managers(base: str, api_key: str, timeout: int = 15):
    """전산 ① 에서 연결 광고주별 현재 담당자 로그인을 받아 온다(읽기 전용)."""
    resp = requests.get(
        f"{base.rstrip('/')}/api/report-sync/client-managers",
        headers={"X-Api-Key": api_key}, timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"전산 담당자 조회 실패 (HTTP {resp.status_code})")
    return ((resp.json() or {}).get("result") or {}).get("items") or []


def _ensure_log_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_owner_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            from_owner INTEGER,
            to_owner INTEGER NOT NULL,
            manager_login TEXT NOT NULL,
            run_id TEXT NOT NULL,
            changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )


def _create_missing_user(conn: sqlite3.Connection, login: str, name: str) -> int:
    """SSO 가 만들 계정을 미리 만든다(같은 username 이면 SSO 가 그대로 재사용).

    로직분석 로그인은 전산 SSO 라 password_hash 는 자리표시자다. 담당자는 '관리부서원'이므로
    role='manager'(SSO 가 로그인 때 팀 기준으로 다시 맞춘다). 반드시 트랜잭션 안에서 부른다.
    """
    import bcrypt
    import secrets
    from datetime import datetime
    now = datetime.now().isoformat()
    pw = bcrypt.hashpw(secrets.token_urlsafe(48).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    conn.execute(
        "INSERT INTO users(username, password_hash, name, role, is_active, created_at, updated_at) "
        "VALUES (?, ?, ?, 'manager', 1, ?, ?)",
        (login, pw, (name or login)[:100], now, now),
    )
    return int(conn.execute("SELECT id FROM users WHERE username=?", (login,)).fetchone()[0])


def run_report_owner_sync(db_path: str | None = None, base: str | None = None,
                          api_key: str | None = None, dry_run: bool = False,
                          run_id: str | None = None) -> dict:
    """전산 담당자에 맞춰 보고서 소유를 정렬한다. dry_run=True 면 규모만 세고 아무것도 안 바꾼다."""
    import logging
    from datetime import datetime
    logger = logging.getLogger("report_owner_sync")

    db_path = db_path or os.getenv("DB_PATH", "/app/data/logic_data.db")
    base = base or os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr")
    api_key = api_key if api_key is not None else os.getenv("ERP_AD_SYNC_API_KEY", "")
    run_id = run_id or datetime.now().strftime("%Y%m%d%H%M%S")

    if not api_key:
        logger.info("보고서 담당자 정렬: ERP_AD_SYNC_API_KEY 미설정 — 건너뜀")
        return {"ok": False, "error": "전산 연동 키가 서버에 설정돼 있지 않습니다."}

    try:
        items = fetch_client_managers(base, api_key)
    except Exception as e:
        logger.warning(f"보고서 담당자 정렬: 전산 조회 실패 — 무동작 ({e})")
        return {"ok": False, "error": "전산 담당자 조회에 실패했습니다(잠시 뒤 다시 시도해 주세요)."}

    # baseline 백업·original_created_by 보존은 인수인계 서비스와 같은 표를 재사용(멱등).
    HandoverTransferService(db_path).initialize()

    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        _ensure_log_table(conn)
        clients_owner = {int(r["id"]): (r["created_by"] if r["created_by"] is not None else 0)
                         for r in conn.execute("SELECT id, created_by FROM clients")}
        users_by_login = {str(r["username"]): int(r["id"])
                          for r in conn.execute("SELECT id, username FROM users")}

        plan = plan_owner_changes(items, clients_owner, users_by_login)
        would_create = len({c.to_login for c in plan.changes if c.to_user_id is None})

        if dry_run:
            logger.info(
                f"🔎 보고서 담당자 정렬 미리보기: 대상 {len(plan.changes)}건 변경 예정 · "
                f"이미 맞음 {plan.aligned_already} · 미배정 {plan.unassigned} · "
                f"업체없음 {plan.unknown_client} · 계정생성 예정 {would_create}"
            )
            return {"ok": True, "dry_run": True, "total": len(items),
                    "would_change": len(plan.changes), "aligned_already": plan.aligned_already,
                    "unassigned": plan.unassigned, "unknown_client": plan.unknown_client,
                    "would_create_accounts": would_create}

        conn.execute("BEGIN IMMEDIATE")
        changed = 0
        created = 0
        for ch in plan.changes:
            to_id = ch.to_user_id
            if to_id is None:
                to_id = _create_missing_user(conn, ch.to_login, ch.to_name)
                created += 1
            moved = conn.execute(
                "UPDATE clients SET created_by=?, updated_at=datetime('now','localtime') "
                "WHERE id=? AND created_by IS NOT ?",
                (to_id, ch.client_id, to_id),
            ).rowcount
            if moved:
                conn.execute(
                    "INSERT INTO report_owner_sync_log(client_id, from_owner, to_owner, manager_login, run_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ch.client_id, ch.from_owner, to_id, ch.to_login, run_id),
                )
                changed += moved
        conn.commit()
        logger.info(
            f"✅ 보고서 담당자 정렬 완료(run {run_id}): 소유 정렬 {changed}건 · 계정 생성 {created} · "
            f"이미 맞음 {plan.aligned_already} · 미배정 {plan.unassigned} · 업체없음 {plan.unknown_client} "
            f"(전산 연결 {len(items)}개)"
        )
        return {"ok": True, "dry_run": False, "run_id": run_id, "total": len(items),
                "changed": changed, "created_accounts": created,
                "aligned_already": plan.aligned_already, "unassigned": plan.unassigned,
                "unknown_client": plan.unknown_client}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"❌ 보고서 담당자 정렬 DB 반영 실패: {e}")
        return {"ok": False, "error": str(e)[:200]}
    finally:
        conn.close()
