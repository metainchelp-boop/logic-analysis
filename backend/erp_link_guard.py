# -*- coding: utf-8 -*-
"""전산(①)과 연결된 업체는 지우지 못하게 (2026-11-28 · 섹션 소식판 ①→② 9/24 요청 · 대표 결정 「추천대로」 ①ⓐ).

왜 만들었나
  9/10~9/21 사이 전산과 연결된 업체 5곳이 로직분석 화면 삭제로 지워져 보고서가 사라지고 전산 연결이
  끊겼다(신고 #262 · 보고서는 백업이 이틀치뿐이라 되살리지 못함). 로직분석은 어느 업체가 전산과
  연결됐는지 따로 기억하지 않았다.

어떻게
  전산 ① 은 이미 매일 04:20 `GET /api/report-sync/client-managers` 로 「연결된 업체 목록」(logic_client_id)을
  보내 준다(report_owner_sync 가 담당자 정렬에만 쓰고 버리던 것). 그 목록을 이 표에 저장하고, 삭제하는
  모든 경로(화면 삭제 · 옛 업체 API 삭제 · 30일 지난 영업 대상·경쟁사 자동 삭제)가 여기 묻는다.
  ⚠️ 전산 쪽 변경은 없다(이미 있는 목록을 받아 저장만 한다).

  - 지우기 직전마다 전산에 새로 묻는다 — 방금 연결된 업체도 막고, 방금 끊은 업체는 바로 풀어 준다.
  - 받기에 실패하거나 목록이 온전하지 않으면(total ≠ items 개수) 저장된 목록으로 판단한다.
  - 새 목록이 비었거나 저장된 목록에서 한꺼번에 20% 넘게 빠지면 바꾸지 않는다(전산 쪽 오류로 보호가
    한꺼번에 풀리지 않게 · 경고 로그).
  - 사람이 지울 때 근거가 전혀 없으면(한 번도 못 받았고 지금도 실패) 막지 않는다(종전처럼).
    30일 자동 삭제는 근거가 없으면 그 회차를 건너뛴다.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

DROP_GUARD_MIN = 20         # 저장된 목록이 이만큼 이상일 때
DROP_GUARD_RATIO = 0.2      # 새 목록이 저장된 것의 20% 넘게 한꺼번에 빠지면 저장하지 않는다(전산 쪽 오류로 보호가 풀리지 않게)


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS erp_linked_clients ("
                 "client_id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS erp_link_sync ("
                 "id INTEGER PRIMARY KEY CHECK (id = 1), synced_at TEXT NOT NULL, linked_count INTEGER NOT NULL)")


def ids_from_items(items) -> set[int]:
    """전산 응답 items → 연결된 로직분석 업체 번호들(숫자가 아닌 것은 버림)."""
    out = set()
    for it in items or []:
        try:
            out.add(int((it or {}).get("logic_client_id")))
        except (TypeError, ValueError):
            continue
    return out


def complete(items, total) -> bool:
    """전산 응답이 온전한가 — 전산은 total = items 개수로 준다(ReportSyncService). 다르거나 total 이 없으면 일부만 온 것으로 본다."""
    return isinstance(total, int) and not isinstance(total, bool) and isinstance(items, list) and total == len(items)


def save_linked_set(conn: sqlite3.Connection, ids: set[int]) -> dict:
    """연결 목록을 통째로 바꿔 저장(한 트랜잭션).
    새 목록이 비었거나, 저장된 목록에서 한꺼번에 많이(20% 넘게) 빠지면 바꾸지 않는다 — 전산 쪽 오류로 보호가 풀리지 않게."""
    ensure_tables(conn)
    old = {int(r[0]) for r in conn.execute("SELECT client_id FROM erp_linked_clients")}
    if not ids and old:
        logger.warning(f"[전산 연결 목록] 새 목록이 비어 있어 저장하지 않음(저장된 {len(old)}곳 유지 · 전산 쪽 확인 필요)")
        return {"saved": False, "reason": "empty", "kept": len(old)}
    dropped = len(old - set(ids))
    if len(old) >= DROP_GUARD_MIN and dropped > len(old) * DROP_GUARD_RATIO:
        logger.warning(f"[전산 연결 목록] 저장된 {len(old)}곳 중 {dropped}곳이 한꺼번에 빠져 저장하지 않음(전산 쪽 확인 필요)")
        return {"saved": False, "reason": "mass-drop", "kept": len(old), "dropped": dropped}
    now = datetime.now().isoformat(timespec="seconds")
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        pass   # 이미 트랜잭션 안
    conn.execute("DELETE FROM erp_linked_clients")
    conn.executemany("INSERT INTO erp_linked_clients(client_id, seen_at) VALUES (?, ?)", [(i, now) for i in sorted(ids)])
    conn.execute("INSERT INTO erp_link_sync(id, synced_at, linked_count) VALUES (1, ?, ?) "
                 "ON CONFLICT(id) DO UPDATE SET synced_at=excluded.synced_at, linked_count=excluded.linked_count",
                 (now, len(ids)))
    conn.commit()
    return {"saved": True, "count": len(ids), "synced_at": now}


def sync_info(conn: sqlite3.Connection):
    ensure_tables(conn)
    row = conn.execute("SELECT synced_at, linked_count FROM erp_link_sync WHERE id = 1").fetchone()
    return {"synced_at": row[0], "count": row[1]} if row else None


def _stored_linked(conn: sqlite3.Connection, ids) -> set[int]:
    ids = [int(i) for i in ids]
    if not ids:
        return set()
    ensure_tables(conn)
    marks = ",".join("?" * len(ids))
    return {int(r[0]) for r in conn.execute(f"SELECT client_id FROM erp_linked_clients WHERE client_id IN ({marks})", ids)}


def _fetch_and_save(conn: sqlite3.Connection, fetch) -> bool:
    try:
        items = fetch()
    except Exception as e:
        logger.warning(f"[전산 연결 목록] 받기 실패 — 저장된 목록으로 판단 ({type(e).__name__}: {str(e)[:80]})")
        return False
    return bool(save_linked_set(conn, ids_from_items(items)).get("saved"))


def _default_fetch():
    """전산에서 연결 목록을 받는다 — 온전한 목록만 돌려주고, 일부만 오면 실패로 본다."""
    api_key = os.getenv("ERP_AD_SYNC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ERP_AD_SYNC_API_KEY 미설정")
    from report_owner_sync import fetch_client_managers_payload
    items, total = fetch_client_managers_payload(os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr"), api_key, timeout=8)
    if not complete(items, total):
        raise RuntimeError(f"전산 연결 목록이 온전하지 않음(total={total!r} · items={len(items) if isinstance(items, list) else '?'})")
    return items


def link_status(conn: sqlite3.Connection, ids, fetch=None):
    """(ids 가운데 전산과 연결된 번호들, 판단 근거가 있나).
    ⚠️ 지우기 직전마다 전산에 새로 묻는다 — 저장본만 보면 방금 연결된 업체를 놓치고, 방금 끊은 업체를 계속 막는다
       (2026-11-28 교차검증 재현: 저장본이 최신이라 묻지 않았고 새로 연결된 업체가 지워졌다).
       받기에 실패하거나 목록이 온전하지 않으면 저장본으로 판단한다. 저장본도 없으면 근거 없음(known=False)."""
    fresh = _fetch_and_save(conn, fetch or _default_fetch)
    known = fresh or sync_info(conn) is not None
    return _stored_linked(conn, ids), known


def stored_linked(conn: sqlite3.Connection, ids) -> set[int]:
    """전산에 묻지 않고 저장본만으로 — 같은 회차에 이미 새로 받았을 때 쓴다."""
    return _stored_linked(conn, ids)


def linked_among(conn: sqlite3.Connection, ids, fetch=None) -> set[int]:
    """사람이 지울 때 — 연결된 번호들. 근거가 전혀 없으면(한 번도 못 받았고 지금도 실패) 막지 않는다(종전처럼)."""
    return link_status(conn, ids, fetch)[0]


BLOCK_MESSAGE = ("전산과 연결된 업체라 지울 수 없어요. 지우면 전산 광고주 화면의 보고서가 사라지고 연결이 끊겨요. "
                 "정말 지워야 하면 전산에서 로직분석 연결을 먼저 끊은 뒤 다시 시도해 주세요.")
