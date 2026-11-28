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

  - 원칙: 지금 전산이 「연결 안 됨」이라고 확인해 준 업체만 지운다. 지우기 직전마다 새로 묻고,
    방금 받은 목록 ∪ 저장본을 연결로 본다 — 방금 연결된 업체도 막고, 방금 끊은 업체는 바로 풀어 준다.
  - 받기에 실패하거나 목록이 온전하지 않으면(total ≠ items 개수) 「확인 못 함」이다.
  - 새 목록이 비었거나 저장된 목록에서 한꺼번에 20% 넘게 빠지면 바로 바꾸지 않는다(전산 쪽 오류로 보호가
    한꺼번에 풀리지 않게 · 경고 로그). 같은 목록이 20시간 넘게 이어지면(다음 날 04:20) 진짜 변화로 받아들인다.
  - 근거가 전혀 없으면(저장본도 없고 지금도 못 받음) 지우지 않는다 — 사람이 지울 때는 「잠시 후 다시」 안내,
    30일 자동 삭제는 그 회차를 건너뛴다(교차검증 반영 · 모르는 채로 지우면 연결 업체일 수 있다).
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from datetime import datetime

logger = logging.getLogger(__name__)

DROP_GUARD_MIN = 20         # 저장된 목록이 이만큼 이상일 때
DROP_GUARD_RATIO = 0.2      # 새 목록이 저장된 것의 20% 넘게 한꺼번에 빠지면 저장하지 않는다(전산 쪽 오류로 보호가 풀리지 않게)
CONFIRM_HOURS = 20          # 거절한 목록(빈 목록 · 대량 누락)이 이만큼 넘게 똑같이 이어지면 진짜 변화로 받아들인다(다음 날 04:20 에 확정)


class LinkFetchError(RuntimeError):
    """우리가 만든 받기 실패 문구 — 로그에 그대로 남겨도 되는 것만(외부 예외 원문은 남기지 않는다)."""


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS erp_linked_clients ("
                 "client_id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS erp_link_sync ("
                 "id INTEGER PRIMARY KEY CHECK (id = 1), synced_at TEXT NOT NULL, linked_count INTEGER NOT NULL, "
                 "fetch_started REAL, pending_hash TEXT, pending_since TEXT)")


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


def _writer(conn: sqlite3.Connection):
    """저장 전용 연결 — 부르는 쪽 트랜잭션과 섞이지 않게 같은 DB 파일에 따로 연다(자동 커밋 · BEGIN IMMEDIATE 를 직접 건다)."""
    try:
        path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    except Exception:
        path = ""
    if not path:
        return conn, False
    w = sqlite3.connect(path, timeout=30, isolation_level=None)
    w.execute("PRAGMA busy_timeout=30000")
    return w, True


def save_linked_set(conn: sqlite3.Connection, ids, started_at: float | None = None) -> dict:
    """연결 목록을 통째로 바꿔 저장. 쓰기 잠금(BEGIN IMMEDIATE) 안에서 확인하고 바꾼다(교차검증 반영 — 잠금 밖에서
    세면 그 사이 다른 요청이 저장한 보호를 빈 목록이 지웠다). 바꾸지 않는 경우:
      - 더 늦게 받기 시작한 목록이 이미 저장됐다(started_at 이 저장된 것보다 이르다 — 늦게 도착한 옛 응답)
      - 새 목록이 비었는데 저장된 것이 있다
      - 저장된 목록(20곳 이상)에서 한꺼번에 20% 넘게 빠진다
    """
    ids = {int(i) for i in ids}
    w, own = _writer(conn)
    try:
        ensure_tables(w)
        w.execute("BEGIN IMMEDIATE")
        try:
            row = w.execute("SELECT fetch_started FROM erp_link_sync WHERE id = 1").fetchone()
            if started_at is not None and row and row[0] is not None and started_at < float(row[0]):
                w.execute("ROLLBACK")
                logger.info("[전산 연결 목록] 더 나중에 받은 목록이 이미 저장돼 이 응답은 버림")
                return {"saved": False, "reason": "stale"}
            old = {int(r[0]) for r in w.execute("SELECT client_id FROM erp_linked_clients")}
            dropped = len(old - ids)
            reason = None
            if not ids and old:
                reason = "empty"
            elif len(old) >= DROP_GUARD_MIN and dropped > len(old) * DROP_GUARD_RATIO:
                reason = "mass-drop"
            now = datetime.now().isoformat(timespec="seconds")
            if reason:
                # 같은 목록이 CONFIRM_HOURS 넘게 이어지면 전산의 진짜 변화로 받아들인다 — 거절만 하면 진짜로 끊은 연결이 영영 막힌다(교차검증 반영)
                digest = hashlib.sha1(",".join(map(str, sorted(ids))).encode()).hexdigest()
                prow = w.execute("SELECT pending_hash, pending_since FROM erp_link_sync WHERE id = 1").fetchone()
                since = None
                if prow and prow[0] == digest and prow[1]:
                    try:
                        since = datetime.fromisoformat(prow[1])
                    except ValueError:
                        since = None
                if since is None or (datetime.now() - since).total_seconds() < CONFIRM_HOURS * 3600:
                    if since is None:
                        w.execute("UPDATE erp_link_sync SET pending_hash=?, pending_since=? WHERE id = 1", (digest, now))
                    w.execute("COMMIT")
                    logger.warning(f"[전산 연결 목록] {'새 목록이 비어' if reason == 'empty' else f'저장된 {len(old)}곳 중 {dropped}곳이 한꺼번에 빠져'} "
                                   f"저장하지 않음(같은 목록이 {CONFIRM_HOURS}시간 넘게 이어지면 받아들임 · 전산 쪽 확인 필요)")
                    return {"saved": False, "reason": reason, "kept": len(old), "dropped": dropped}
                logger.info(f"[전산 연결 목록] 거절했던 목록이 {CONFIRM_HOURS}시간 넘게 이어져 진짜 변화로 받아들임({reason} · {dropped}곳 빠짐)")
            w.execute("DELETE FROM erp_linked_clients")
            w.executemany("INSERT INTO erp_linked_clients(client_id, seen_at) VALUES (?, ?)", [(i, now) for i in sorted(ids)])
            w.execute("INSERT INTO erp_link_sync(id, synced_at, linked_count, fetch_started, pending_hash, pending_since) "
                      "VALUES (1, ?, ?, ?, NULL, NULL) "
                      "ON CONFLICT(id) DO UPDATE SET synced_at=excluded.synced_at, linked_count=excluded.linked_count, "
                      "fetch_started=excluded.fetch_started, pending_hash=NULL, pending_since=NULL", (now, len(ids), started_at))
            w.execute("COMMIT")
            return {"saved": True, "count": len(ids), "synced_at": now}
        except Exception:
            try:
                w.execute("ROLLBACK")
            except Exception:
                pass
            raise
    finally:
        if own:
            w.close()


def _has_tables(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='erp_linked_clients'").fetchone()[0] == 1
    except sqlite3.Error:
        return False


def sync_info(conn: sqlite3.Connection):
    """마지막으로 저장한 때와 곳 수(없으면 None). 읽기만 — 표가 없어도 만들지 않는다."""
    if not _has_tables(conn):
        return None
    row = conn.execute("SELECT synced_at, linked_count FROM erp_link_sync WHERE id = 1").fetchone()
    return {"synced_at": row[0], "count": row[1]} if row else None


def _stored_linked(conn: sqlite3.Connection, ids) -> set[int]:
    ids = [int(i) for i in ids]
    if not ids or not _has_tables(conn):
        return set()
    marks = ",".join("?" * len(ids))
    return {int(r[0]) for r in conn.execute(f"SELECT client_id FROM erp_linked_clients WHERE client_id IN ({marks})", ids)}


def stored_linked(conn: sqlite3.Connection, ids) -> set[int]:
    """전산에 묻지 않고 저장본만으로."""
    return _stored_linked(conn, ids)


def _fetch_ids(fetch):
    """전산에서 온전한 연결 목록을 받아 번호 집합으로. 실패·불완전이면 None."""
    try:
        items = fetch()
    except Exception as e:
        # 외부 예외 원문은 남기지 않는다(주소·헤더 값이 섞일 수 있다) — 우리가 만든 문구(LinkFetchError)만 남긴다
        detail = f": {e}" if isinstance(e, LinkFetchError) else ""
        logger.warning(f"[전산 연결 목록] 받기 실패 — 연결 여부 미확인 ({type(e).__name__}{detail})")
        return None
    return ids_from_items(items)


def _default_fetch():
    """전산에서 연결 목록을 받는다 — 온전한 목록만 돌려주고, 일부만 오면 실패로 본다."""
    api_key = os.getenv("ERP_AD_SYNC_API_KEY", "")
    if not api_key:
        raise LinkFetchError("ERP_AD_SYNC_API_KEY 미설정")
    from report_owner_sync import fetch_client_managers_payload
    items, total = fetch_client_managers_payload(os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr"), api_key, timeout=8)
    if not complete(items, total):
        raise LinkFetchError(f"전산 연결 목록이 온전하지 않음(total={total!r} · items={len(items) if isinstance(items, list) else '?'})")
    return items


def link_status(conn: sqlite3.Connection, ids, fetch=None, save: bool = True):
    """(ids 가운데 전산과 연결된 번호들, 지금 전산이 확인해 줬나).

    원칙: **지금 전산이 「연결 안 됨」이라고 확인해 준 업체만 지운다**(교차검증 반영).
      - 매번 전산에 새로 묻는다. 온전한 목록을 받았을 때만 known=True.
      - 연결로 보는 것 = 방금 받은 목록 ∪ 저장본. 저장을 거절한 경우(늦게 온 옛 응답 · 빈 목록 · 대량 누락)에도
        방금 받은 목록의 연결은 막는다 — 저장 거절이 보호를 줄이지 않게.
      - 받기 실패·불완전이면 known=False — 사람이 지울 땐 「잠시 후 다시」, 자동 삭제는 그 회차를 건너뛴다.
        저장본이 오래됐어도 「확인됨」으로 치지 않는다.
      - save=False(삭제 미리보기)면 아무것도 쓰지 않는다(표가 없어도 만들지 않음).
    """
    want = {int(i) for i in ids}
    started = time.time()
    fresh = _fetch_ids(fetch or _default_fetch)
    if fresh is not None and save:
        save_linked_set(conn, fresh, started_at=started)
    hit = _stored_linked(conn, want) | (fresh & want if fresh is not None else set())
    return hit, fresh is not None


def linked_among(conn: sqlite3.Connection, ids, fetch=None) -> set[int]:
    """연결된 번호들만(확인 여부는 버림). 지우는 쪽은 link_status 로 확인 여부까지 본다."""
    return link_status(conn, ids, fetch)[0]


UNKNOWN_MESSAGE = ("전산 연결 여부를 지금 확인하지 못해 지울 수 없어요. 잠시 후 다시 시도해 주세요.")
BLOCK_MESSAGE = ("전산과 연결된 업체라 지울 수 없어요. 지우면 전산 광고주 화면의 보고서가 사라지고 연결이 끊겨요. "
                 "정말 지워야 하면 전산에서 로직분석 연결을 먼저 끊은 뒤 다시 시도해 주세요.")
