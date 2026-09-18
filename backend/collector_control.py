"""수집 켜고 끄기 — 화면에서 제어하는 스위치 한 곳. (대표 확정 2026-09-18)

## 왜 만드나

지금까지 수집을 멈추려면 **확장 팝업으로 가야만** 했다. 대표 지시:
「굳이 확장에서 끄지 않더라도 버튼을 만들어서 화면에서도 끄고 키고 할 수 있게」.

## 어떻게 도나

- 화면이 이 표에 「멈춤」을 적는다(`set_paused`).
- 확장이 매 회차 시작 전에 `/api/collector/keywords` 응답의 `paused` 를 본다.
  멈춤이면 그 회차를 통째로 건너뛴다(네이버 요청 0건).
- 기계별(worker)로도, 전체(worker=-1)로도 끌 수 있다.

## 왜 파일을 따로 뒀나 (split_rule·collect_slot·keyword_limit 과 같은 이유)

① 쓰는 곳이 둘 이상 — 수집 배분(collector)과 화면 상태 조회.
② 배포 게이트에 fastapi 가 없어 collector.py 를 import 못 한다. 여기는 stdlib 만.

## ⚠️ 안전 원칙 — 판정 실패는 「멈춤」이 아니라 「돎」이다

조회가 실패하면 **멈추지 않는다**(is_paused→False). 스위치 표가 깨졌다고
수집이 통째로 서 버리는 쪽이 더 나쁜 고장이다. 멈춤은 **명시적으로 적혔을 때만**.
"""

import sqlite3

ALL = -1   # worker=-1 = 전체 기계


def ensure_table(conn) -> None:
    """제어 표 보장(멱등)."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collector_control (
                worker INTEGER PRIMARY KEY,   -- -1=전체 · 0,1,2…=그 기계(0-base)
                stopped INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                updated_by TEXT DEFAULT ''
            )
        """)
        conn.commit()
    except sqlite3.Error:
        pass


def is_paused(conn, worker=None) -> bool:
    """이 기계(worker, 0-base)가 지금 멈춤인가.

    전체 멈춤(worker=-1)이 켜져 있으면 모든 기계가 멈춤이다.
    worker 를 안 주면 전체 멈춤만 본다.
    ⚠️ 조회 실패 시 False(=돎). 스위치가 깨져도 수집은 계속되게.
    """
    try:
        ensure_table(conn)
        row = conn.execute(
            "SELECT stopped FROM collector_control WHERE worker = ?", (ALL,)).fetchone()
        if row and int(row[0]) == 1:
            return True
        if worker is None:
            return False
        try:
            w = int(worker)
        except (TypeError, ValueError):
            return False
        if w < 0:
            return False
        row = conn.execute(
            "SELECT stopped FROM collector_control WHERE worker = ?", (w,)).fetchone()
        return bool(row and int(row[0]) == 1)
    except sqlite3.Error:
        return False


def set_paused(conn, worker, stopped, by="") -> bool:
    """멈춤/재개를 적는다. worker=-1 = 전체. 성공하면 True."""
    try:
        ensure_table(conn)
        w = int(worker)
        s = 1 if stopped else 0
        conn.execute(
            "INSERT INTO collector_control(worker, stopped, updated_at, updated_by) "
            "VALUES(?,?,datetime('now','localtime'),?) "
            "ON CONFLICT(worker) DO UPDATE SET "
            "  stopped=excluded.stopped, updated_at=excluded.updated_at, "
            "  updated_by=excluded.updated_by",
            (w, s, str(by or "")[:60]))
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def get_state(conn) -> dict:
    """화면이 그릴 현재 상태 — {"all": bool, "workers": {w: {stopped, updated_at, by}}}."""
    out = {"all": False, "workers": {}}
    try:
        ensure_table(conn)
        for r in conn.execute(
                "SELECT worker, stopped, updated_at, updated_by FROM collector_control"):
            w, s, at, by = r[0], int(r[1]), r[2], r[3]
            if w == ALL:
                out["all"] = (s == 1)
                out["all_updated_at"] = at
                out["all_updated_by"] = by
            else:
                out["workers"][str(w)] = {"stopped": (s == 1), "updated_at": at, "by": by}
    except sqlite3.Error:
        pass
    return out
