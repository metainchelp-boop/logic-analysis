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
  - 받기에 실패하거나 목록이 온전하지 않으면(items 없음 · total ≠ items 개수 · 번호 못 읽는 줄) 「확인 못 함」이다.
  - 저장본은 「연결을 본 기록」이다. 응답에 보인 연결은 언제나 더하고(늦게 온 응답이라도), 해제는 그 연결을 마지막으로
    본 응답보다 늦게 받기 시작한 응답만 한다. 빈 목록이나 한꺼번에 20% 넘는 해제는 보류하고, 같은 목록이 20시간 넘게
    이어지면(다음 날 04:20) 해제한다.
  - 지우는 쪽은 네트워크를 다녀온 뒤 쓰기 트랜잭션 안에서 저장본으로 한 번 더 확인한다.
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
    # seen_started = 이 업체를 연결로 본 응답 중 가장 늦게 받기 시작한 시각 — 해제는 그보다 늦게 받기 시작한 응답만 할 수 있다
    conn.execute("CREATE TABLE IF NOT EXISTS erp_linked_clients ("
                 "client_id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL, seen_started REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS erp_link_sync ("
                 "id INTEGER PRIMARY KEY CHECK (id = 1), synced_at TEXT NOT NULL, linked_count INTEGER NOT NULL, "
                 "pending_hash TEXT, pending_since TEXT)")


def ids_from_items(items) -> set[int]:
    """전산 응답 items → 연결된 로직분석 업체 번호들(숫자가 아닌 것은 버림)."""
    out = set()
    for it in items or []:
        try:
            out.add(int((it or {}).get("logic_client_id")))
        except (TypeError, ValueError):
            continue
    return out


def _valid_id(it) -> bool:
    if not isinstance(it, dict):
        return False
    v = it.get("logic_client_id")
    if isinstance(v, bool):
        return False
    try:
        int(v)
        return True
    except (TypeError, ValueError):
        return False


def complete(items, total) -> bool:
    """전산 응답이 온전한가 — 전산은 total = items 개수로 준다(ReportSyncService).
    items 칸이 없거나(목록이 아님) · total 이 없거나 다르거나 · 번호를 못 읽는 줄이 하나라도 있으면 온전하지 않다(교차검증 반영)."""
    return (isinstance(total, int) and not isinstance(total, bool) and isinstance(items, list)
            and total == len(items) and all(_valid_id(it) for it in items))


def _has_tables(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='erp_linked_clients'").fetchone()[0] == 1
    except sqlite3.Error:
        return False


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


def _plan(c: sqlite3.Connection, fresh: set[int], started_at: float):
    """한 응답을 반영하면 무엇이 바뀌는지 계산만 한다(읽기만 · 표가 없으면 빈 저장본).
    반환: (지금 저장본 {번호: seen_started}, 해제할 번호들, 해제를 보류하나, 보류 이유, 덧정보)
      - 해제 후보 = 저장본에 있는데 이 응답에 없고, 이 응답보다 먼저 받기 시작한 응답에서만 보인 것
        (더 늦게 받기 시작한 응답이 본 연결은 늦게 도착한 옛 응답이 해제할 수 없다 — 교차검증 반영)
      - 빈 목록이거나 저장본(20곳 이상)의 20% 넘게 한꺼번에 해제되면 보류 — 같은 목록이 CONFIRM_HOURS 넘게 이어지면 해제한다"""
    old, row = {}, None
    if _has_tables(c):
        old = {int(r[0]): (float(r[1]) if r[1] is not None else 0.0)
               for r in c.execute("SELECT client_id, seen_started FROM erp_linked_clients")}
        row = c.execute("SELECT pending_hash, pending_since FROM erp_link_sync WHERE id = 1").fetchone()
    remove = {i for i, seen in old.items() if i not in fresh and seen < started_at}
    reason = None
    if remove and not fresh:
        reason = "empty"
    elif len(old) >= DROP_GUARD_MIN and len(remove) > len(old) * DROP_GUARD_RATIO:
        reason = "mass-drop"
    if not reason:
        return old, remove, False, None, {}
    digest = hashlib.sha1(",".join(map(str, sorted(fresh))).encode()).hexdigest()
    same = bool(row and row[0] == digest and row[1])
    if same:
        try:
            if (datetime.now() - datetime.fromisoformat(row[1])).total_seconds() >= CONFIRM_HOURS * 3600:
                return old, remove, False, reason + "-confirmed", {}
        except ValueError:
            pass
    return old, remove, True, reason, {"digest": digest, "pending_same": same}


def apply_response(conn: sqlite3.Connection, fresh, started_at: float) -> dict:
    """온전한 응답 하나를 저장본에 반영한다(따로 연 연결 · 쓰기 잠금 안).
    ① 이 응답에 보인 연결은 **언제나** 더한다(늦게 온 응답 · 보류된 응답이라도) — 관측한 보호를 잃지 않게.
    ② 해제는 _plan 이 허락한 것만(이 응답보다 늦게 본 연결은 해제하지 않음 · 대량 해제는 보류)."""
    fresh = {int(i) for i in fresh}
    w, own = _writer(conn)
    try:
        ensure_tables(w)
        w.execute("BEGIN IMMEDIATE")
        try:
            old, remove, held, reason, x = _plan(w, fresh, started_at)
            now = datetime.now().isoformat(timespec="seconds")
            for i in fresh:
                w.execute("INSERT INTO erp_linked_clients(client_id, seen_at, seen_started) VALUES (?, ?, ?) "
                          "ON CONFLICT(client_id) DO UPDATE SET seen_at=excluded.seen_at, "
                          "seen_started=MAX(COALESCE(seen_started, 0), excluded.seen_started)", (i, now, started_at))
            if held:
                if not x.get("pending_same"):
                    w.execute("INSERT INTO erp_link_sync(id, synced_at, linked_count, pending_hash, pending_since) VALUES (1, ?, ?, ?, ?) "
                              "ON CONFLICT(id) DO UPDATE SET pending_hash=excluded.pending_hash, pending_since=excluded.pending_since",
                              (now, len(old), x["digest"], now))
                why = "새 목록이 비어" if reason == "empty" else "저장된 %s곳 중 %s곳이 한꺼번에 빠져" % (len(old), len(remove))
                logger.warning(f"[전산 연결 목록] {why} 해제를 보류(새 연결은 더함 · 같은 목록이 {CONFIRM_HOURS}시간 넘게 이어지면 해제 · 전산 쪽 확인 필요)")
            else:
                if remove:
                    marks = ",".join("?" * len(remove))
                    # 지우는 순간에도 이 응답보다 늦게 본 연결은 남긴다(잠금 안이라 위 계산과 같지만 한 번 더)
                    w.execute(f"DELETE FROM erp_linked_clients WHERE client_id IN ({marks}) AND COALESCE(seen_started, 0) < ?",
                              list(remove) + [started_at])
                if reason:
                    logger.info(f"[전산 연결 목록] 보류했던 해제를 {CONFIRM_HOURS}시간 넘게 같은 목록이라 반영({reason} · {len(remove)}곳)")
            count = w.execute("SELECT COUNT(*) FROM erp_linked_clients").fetchone()[0]
            w.execute("INSERT INTO erp_link_sync(id, synced_at, linked_count, pending_hash, pending_since) VALUES (1, ?, ?, NULL, NULL) "
                      "ON CONFLICT(id) DO UPDATE SET synced_at=excluded.synced_at, linked_count=excluded.linked_count"
                      + ("" if held else ", pending_hash=NULL, pending_since=NULL"), (now, count))
            w.execute("COMMIT")
            return {"saved": not held, "held": held, "reason": reason, "added": len(fresh - set(old)),
                    "removed": 0 if held else len(remove), "count": count}
        except Exception:
            try:
                w.execute("ROLLBACK")
            except Exception:
                pass
            raise
    finally:
        if own:
            w.close()


def save_linked_set(conn: sqlite3.Connection, ids, started_at: float | None = None) -> dict:
    """온전한 연결 목록 하나를 반영(apply_response 와 같음 · 받기 시작 시각을 모르면 지금)."""
    return apply_response(conn, ids, time.time() if started_at is None else started_at)


def sync_info(conn: sqlite3.Connection):
    """마지막으로 반영한 때와 곳 수(없으면 None). 읽기만 — 표가 없어도 만들지 않는다."""
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
    """전산에 묻지 않고 저장본만으로 — 지우는 쓰기 트랜잭션 안에서 마지막으로 다시 확인할 때 쓴다."""
    return _stored_linked(conn, ids)


def _fetch_ids(fetch):
    """전산에서 온전한 연결 목록을 받아 번호 집합으로. 실패·불완전이면 None."""
    try:
        items = fetch()
    except Exception as e:
        # 외부 예외 원문·응답 값은 남기지 않는다 — 우리가 만든 문구(LinkFetchError)만 남긴다
        detail = f": {e}" if isinstance(e, LinkFetchError) else ""
        logger.warning(f"[전산 연결 목록] 받기 실패 — 연결 여부 미확인 ({type(e).__name__}{detail})")
        return None
    return ids_from_items(items)


def _default_fetch():
    """전산에서 연결 목록을 받는다 — 온전한 목록만 돌려주고, 일부만 오거나 모양이 다르면 실패로 본다."""
    api_key = os.getenv("ERP_AD_SYNC_API_KEY", "")
    if not api_key:
        raise LinkFetchError("ERP_AD_SYNC_API_KEY 미설정")
    from report_owner_sync import fetch_client_managers_payload
    items, total = fetch_client_managers_payload(os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr"), api_key, timeout=8)
    if not complete(items, total):
        raise LinkFetchError("전산 연결 목록이 온전하지 않음(개수가 맞지 않거나 형식이 다름)")
    return items


def link_status(conn: sqlite3.Connection, ids, fetch=None, save: bool = True):
    """(ids 가운데 전산과 연결된 번호들, 지금 전산이 확인해 줬나).

    원칙: **지금 전산이 「연결 안 됨」이라고 확인해 준 업체만 지운다**(교차검증 반영).
      - 매번 전산에 새로 묻는다. 온전한 목록을 받았을 때만 known=True. 실패·불완전이면 known=False —
        사람이 지울 땐 「잠시 후 다시」, 자동 삭제는 그 회차를 건너뛴다.
      - save=True 면 응답을 저장본에 반영(apply_response)한 뒤 저장본으로 답한다. save=False(삭제 미리보기)면
        아무것도 쓰지 않고 같은 규칙(_plan)으로 반영했을 때의 결과를 계산한다 — 미리보기와 실제 삭제가 같은 답을 낸다.
      ⚠️ 이 답은 네트워크를 다녀온 시점의 것이다 — 지우는 쪽은 쓰기 트랜잭션 안에서 stored_linked 로 한 번 더 본다.
    """
    want = {int(i) for i in ids}
    started = time.time()
    fresh = _fetch_ids(fetch or _default_fetch)
    if fresh is None:
        return _stored_linked(conn, want), False
    if save:
        apply_response(conn, fresh, started)
        return _stored_linked(conn, want), True
    old, remove, held, _, _ = _plan(conn, fresh, started)
    effective = set(old) | fresh
    if not held:
        effective -= remove
    return effective & want, True


def linked_among(conn: sqlite3.Connection, ids, fetch=None) -> set[int]:
    """연결된 번호들만(확인 여부는 버림). 지우는 쪽은 link_status 로 확인 여부까지 본다."""
    return link_status(conn, ids, fetch)[0]


UNKNOWN_MESSAGE = ("전산 연결 여부를 지금 확인하지 못해 지울 수 없어요. 잠시 후 다시 시도해 주세요.")
BLOCK_MESSAGE = ("전산과 연결된 업체라 지울 수 없어요. 지우면 전산 광고주 화면의 보고서가 사라지고 연결이 끊겨요. "
                 "정말 지워야 하면 전산에서 로직분석 연결을 먼저 끊은 뒤 다시 시도해 주세요.")
