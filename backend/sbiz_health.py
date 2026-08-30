"""소상공인365 상권 API 가 살아 있는지 기록해 둔다 (대표 확정 2026-08-30, 안 「나」).

⚠️ 이 파일이 생긴 이유 — **죽어도 아무도 몰랐다.**
   2026-08-30 11:50~12:24 사이 상권 API 가 실제로 죽어 있었다(503). 그런데
   `get_place_sbiz` 는 실패하면 조용히 None 을 돌려주고 화면은 상권 카드만 빼므로,
   서비스는 멀쩡해 보이고 로그에도 **호출이 없으면 아무 흔적이 안 남는다**.
   그날 「언제부터 죽었나」를 물었을 때 답할 방법이 없었다 —
   컨테이너 로그에 `[sbiz365]` 가 **한 줄도 없었기 때문**이다(그 사이 아무도 안 돌렸다).

   그래서 두 가지를 한다.
     ① 직원이 돌릴 때마다 결과를 남긴다(성공/실패·사유·시각)
     ② 아무도 안 돌려도 **매일 한 번 스스로 찔러 본다** — 이게 핵심이다.
        ①만 있으면 「아무도 안 썼다」와 「죽었다」를 여전히 못 가른다.

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다
   (tracking_eligibility·split_rule·keyword_mute 와 같은 이유).

⚠️ **어떤 실패도 밖으로 내보내지 않는다.** 기록이 안 되는 것보다 분석이 멈추는 게 훨씬 나쁘다.
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# 자가 점검이 쓰는 표본 — 한 곳이면 그 동네만 통계가 없어도 실패로 보인다.
# 성격이 다른 세 곳을 두고 **하나라도 되면 살아 있는 것**으로 본다.
PROBE_SAMPLES = (("성수동", "카페"), ("구로동", "분식"), ("역삼동", "한식"))


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn) -> None:
    """멱등. 이미 있으면 아무 일도 안 한다.

    ⚠️ 진행 중인 트랜잭션 안에서 commit 하지 않는다 — 8/29 에 한 번 데인 자리다.
       (BEGIN IMMEDIATE 구간을 중간 commit 이 조용히 끝내면 lost-update 방지가 무력해진다.)
    """
    try:
        in_tx = conn.in_transaction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sbiz_health(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                ok        INTEGER NOT NULL,
                reason    TEXT DEFAULT '',
                source    TEXT DEFAULT ''    -- 'probe'(자가 점검) / 'live'(직원이 돌림)
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sbiz_health_at ON sbiz_health(checked_at)")
        if not in_tx:
            conn.commit()
    except Exception:
        pass


def record(ok: bool, reason: str = "", source: str = "live", conn=None) -> None:
    """한 번의 호출 결과를 남긴다. 실패해도 예외를 밖으로 내지 않는다."""
    own = conn is None
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        conn.execute(
            "INSERT INTO sbiz_health(checked_at, ok, reason, source) VALUES(?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 1 if ok else 0,
             (reason or "")[:80], (source or "")[:16]))
        if own or not conn.in_transaction:
            conn.commit()
    except Exception:
        pass
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def summary(conn=None) -> dict:
    """「언제부터 안 되나」에 답하는 값들. 조회 실패는 빈 dict."""
    own = conn is None
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        out = {}
        r = conn.execute("SELECT MAX(id) i, MAX(checked_at) m FROM sbiz_health WHERE ok=1").fetchone()
        last_ok_id = r["i"] if r else None
        out["last_ok"] = r["m"] if r else None
        r = conn.execute("SELECT MAX(checked_at) m FROM sbiz_health").fetchone()
        out["last_any"] = r["m"] if r else None
        # 마지막 성공 이후 실패가 몇 번 이어졌나 — 이 값이 크면 며칠째 죽은 것이다.
        # ⚠️ **시각이 아니라 id 로 센다.** 초 단위 시각이라 같은 초에 성공과 실패가 들어오면
        #    `checked_at > 마지막성공` 이 거짓이 돼 실패가 통째로 안 세어진다(테스트가 잡았다).
        if last_ok_id:
            r = conn.execute("SELECT COUNT(*) n FROM sbiz_health WHERE ok=0 AND id > ?",
                             (last_ok_id,)).fetchone()
        else:
            r = conn.execute("SELECT COUNT(*) n FROM sbiz_health WHERE ok=0").fetchone()
        out["fail_streak"] = r["n"] if r else 0
        rows = conn.execute(
            "SELECT reason, COUNT(*) n FROM sbiz_health "
            " WHERE ok=0 AND checked_at >= datetime('now','localtime','-7 day') "
            " GROUP BY reason ORDER BY n DESC").fetchall()
        out["recent_fail_reasons"] = {r["reason"]: r["n"] for r in rows}
        r = conn.execute(
            "SELECT COUNT(*) n, SUM(ok) k FROM sbiz_health "
            " WHERE checked_at >= datetime('now','localtime','-7 day')").fetchone()
        out["last7_total"] = (r["n"] or 0) if r else 0
        out["last7_ok"] = (r["k"] or 0) if r else 0
        return out
    except Exception:
        return {}
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def run_probe(get_place_sbiz=None) -> dict:
    """매일 1회 자가 점검. 표본 중 **하나라도 되면 살아 있는 것**으로 본다.

    ⚠️ 표본을 하나만 두면 그 동네·업종에 통계가 없을 때 API 장애로 오인한다.
    ⚠️ get_place_sbiz 를 인자로 받는다 — 테스트가 네트워크 없이 부를 수 있어야 한다.
    """
    if get_place_sbiz is None:
        from sbiz365 import get_place_sbiz as _f
        get_place_sbiz = _f

    tried, ok, last_reason = 0, False, ""
    for region, industry in PROBE_SAMPLES:
        tried += 1
        why = {}
        try:
            blk = get_place_sbiz(region, industry, reason=why)
        except Exception as e:
            blk, why = None, {"code": f"exc:{type(e).__name__}"}
        if blk:
            ok = True
            break
        last_reason = str(why.get("code") or why or "unknown")[:80]

    record(ok, "" if ok else last_reason, source="probe")
    return {"ok": ok, "tried": tried, "reason": last_reason}
