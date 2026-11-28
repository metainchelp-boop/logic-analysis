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

  - 저장된 목록에 있으면 「연결됨」. 그때만 전산에 한 번 더 물어(1분에 한 번까지) 방금 연결을 끊었으면
    바로 풀어 준다 — 전산에서 끊고 다음 날까지 기다리지 않게.
  - 목록을 한 번도 못 받았거나 36시간 넘게 못 받았으면 삭제할 때 한 번 받아 본다. 그래도 못 받으면
    저장된 목록(있으면)으로 판단한다 — 전산이 잠깐 안 될 때 삭제가 통째로 막히지 않게.
  - 새로 받은 목록이 비어 있는데 저장된 목록이 있으면 바꾸지 않는다(전산 쪽 오류로 보호가 한꺼번에
    풀리지 않게 · 경고 로그).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

STALE_HOURS = 36            # 이보다 오래 못 받았으면 삭제할 때 한 번 받아 본다
RECHECK_MIN_SEC = 60        # 「연결됨」일 때 전산에 다시 묻는 간격(프로세스마다)
_recheck_lock = threading.Lock()
_last_recheck = 0.0


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


def save_linked_set(conn: sqlite3.Connection, ids: set[int]) -> dict:
    """연결 목록을 통째로 바꿔 저장(한 트랜잭션). 새 목록이 비었는데 저장된 것이 있으면 바꾸지 않는다."""
    ensure_tables(conn)
    old = conn.execute("SELECT COUNT(*) FROM erp_linked_clients").fetchone()[0]
    if not ids and old:
        logger.warning(f"[전산 연결 목록] 새 목록이 비어 있어 저장하지 않음(저장된 {old}곳 유지 · 전산 쪽 확인 필요)")
        return {"saved": False, "reason": "empty", "kept": old}
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
        logger.warning(f"[전산 연결 목록] 받기 실패 — 저장된 목록으로 판단 ({type(e).__name__})")
        return False
    return bool(save_linked_set(conn, ids_from_items(items)).get("saved"))


def _default_fetch():
    api_key = os.getenv("ERP_AD_SYNC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ERP_AD_SYNC_API_KEY 미설정")
    from report_owner_sync import fetch_client_managers
    return fetch_client_managers(os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr"), api_key, timeout=8)


def _is_stale(info) -> bool:
    if not info:
        return True
    try:
        age = (datetime.now() - datetime.fromisoformat(info["synced_at"])).total_seconds()
    except Exception:
        return True
    return age > STALE_HOURS * 3600


def linked_among(conn: sqlite3.Connection, ids, fetch=None) -> set[int]:
    """ids 가운데 전산과 연결된 업체 번호. 지우기 직전에 부른다."""
    global _last_recheck
    fetch = fetch or _default_fetch
    if _is_stale(sync_info(conn)):
        _fetch_and_save(conn, fetch)
    hit = _stored_linked(conn, ids)
    if hit:
        # 방금 전산에서 연결을 끊었을 수 있다 — 한 번 더 물어 최신으로(1분에 한 번까지)
        with _recheck_lock:
            due = time.time() - _last_recheck >= RECHECK_MIN_SEC
            if due:
                _last_recheck = time.time()
        if due and _fetch_and_save(conn, fetch):
            hit = _stored_linked(conn, ids)
    return hit


BLOCK_MESSAGE = ("전산과 연결된 업체라 지울 수 없어요. 지우면 전산 광고주 화면의 보고서가 사라지고 연결이 끊겨요. "
                 "정말 지워야 하면 전산에서 로직분석 연결을 먼저 끊은 뒤 다시 시도해 주세요.")
