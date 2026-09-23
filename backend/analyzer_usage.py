"""분석기별 사용량 — 스토어 분석과 플레이스 분석을 **따로** 센다 (대표 지시 2026-09-23).

⚠️ 이 파일이 생긴 이유 — **플레이스 분석은 몇 번 쓰였는지 어디에도 안 남았다.**
   종전 사용량 표 `daily_usage`(설정 → 「📊 로직 분석 실행 건수」)는 **스토어 분석 화면**이
   분석 버튼을 누를 때(`App.jsx handleSearch` → `/api/cd/usage/increment`)만 올린다.
   플레이스 분석 화면(`PlaceAnalysisPage.jsx`)은 그 경로를 부르지 않는다.
   서버 접속 기록에서도 둘은 같은 주소(`/api/seo/analyze`)라 갈리지 않는다(9/23 점검).

⚠️ **스토어 숫자는 옮기지 않는다** — `daily_usage` 는 영업사원 하루 한도(30회)의 근거다.
   거기에 플레이스를 더하면 **플레이스를 돌린 만큼 스토어 분석이 막힌다**(동작 변경).
   그래서 스토어는 `daily_usage` 를 그대로 읽고, 플레이스만 이 표에 따로 센다.

⚠️ **세는 단위가 다르다** — 스토어는 「분석 버튼 한 번」(화면이 센다), 플레이스는
   「서버가 분석을 한 번 돌린 것」(서버가 센다). 플레이스 화면의 「다시 계산」도 서버에서
   분석을 한 번 더 돌리므로 1회로 셈한다.
⚠️ **소급하지 않는다** — 이 표가 생기기 전의 플레이스 분석은 셀 근거가 없다(`since` 로 밝힌다).

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다.
⚠️ **어떤 실패도 밖으로 내보내지 않는다** — 세다가 실패했다고 분석이 실패하면 안 된다.
"""

import os
import sqlite3
from datetime import date
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# 이 표가 세는 분석기. 스토어는 여기서 세지 않는다(위 설명 — daily_usage 가 센다).
ANALYZERS = ("place",)

# 플레이스 분석 하루 한도(대표 확정 2026-09-23 — 「플레이스 분석도 한도는 정하자. 쇼핑 쪽에 맞춰서」).
# ⚠️ 스토어 한도(`client_dashboard.VIEWER_DAILY_LIMIT` = 30)와 **같은 수준**이되 **따로 센다** —
#    스토어 30회를 다 쓴 영업사원도 플레이스는 30회 돌릴 수 있고, 그 반대도 같다.
# ⚠️ 스토어와 다른 점 하나 — 스토어는 화면이 한도를 확인하고(서버는 막지 않는다), 플레이스는
#    **서버가 막는다**(`main.seo_analyze` 플레이스 분기). 화면을 우회해도 한도가 지켜진다.
PLACE_VIEWER_DAILY_LIMIT = 30
# 한도가 없는 역할 — 스토어 `check_usage` 와 같은 목록(관리자·매니저는 무제한).
UNLIMITED_ROLES = ("admin", "superadmin", "manager")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn) -> None:
    """멱등. 진행 중인 트랜잭션 안에서는 commit 하지 않는다."""
    try:
        in_tx = conn.in_transaction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyzer_usage(
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                usage_date TEXT NOT NULL,
                user_id    INTEGER NOT NULL DEFAULT 0,
                analyzer   TEXT NOT NULL,
                runs       INTEGER NOT NULL DEFAULT 0,   -- 돌린 횟수(실패 포함)
                fails      INTEGER NOT NULL DEFAULT 0,   -- 그중 결과를 못 낸 횟수
                UNIQUE(usage_date, user_id, analyzer)
            )""")
        if not in_tx:
            conn.commit()
    except Exception:
        pass


def record(user_id, analyzer: str, ok: bool = True, conn=None,
           today: Optional[str] = None) -> bool:
    """분석 한 번을 센다. 성공하면 True. 어떤 실패도 밖으로 내보내지 않는다."""
    if analyzer not in ANALYZERS:
        return False
    own = conn is None
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        conn.execute(
            "INSERT INTO analyzer_usage(usage_date, user_id, analyzer, runs, fails) "
            "VALUES(?,?,?,1,?) "
            "ON CONFLICT(usage_date, user_id, analyzer) "
            "DO UPDATE SET runs = runs + 1, fails = fails + excluded.fails",
            (today or date.today().isoformat(), uid, analyzer, 0 if ok else 1))
        if own:
            conn.commit()
        return True
    except Exception:
        return False
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def limit_for(role, analyzer: str) -> int:
    """그 역할의 하루 한도. -1 = 무제한. 모르는 분석기는 한도 없음(이 모듈이 세지 않는 것)."""
    if analyzer != "place":
        return -1
    return -1 if (role or "") in UNLIMITED_ROLES else PLACE_VIEWER_DAILY_LIMIT


def usage_check(user_id, role, analyzer: str = "place", conn=None,
                today: Optional[str] = None) -> dict:
    """오늘 몇 번 썼고 더 돌릴 수 있는가 — 스토어 `/cd/usage/check` 와 **같은 모양**.

    ⚠️ 한도는 **결과를 낸 횟수(runs − fails)** 로 센다 — 서버 오류로 실패한 것까지 세면
       직원이 우리 고장 때문에 하루 몫을 잃는다.
    ⚠️ 조회가 실패하면 **막지 않는다**(can_query=True · error=True) — 스토어 `check_usage` 와
       같은 방향이다. 세는 장치가 아파서 분석이 막히는 쪽이 더 나쁜 고장이다.
    """
    limit = limit_for(role, analyzer)
    t = today or date.today().isoformat()
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    own = conn is None
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        r = conn.execute(
            "SELECT COALESCE(SUM(runs - fails), 0) n FROM analyzer_usage "
            " WHERE usage_date=? AND user_id=? AND analyzer=?", (t, uid, analyzer)).fetchone()
        used = int((r[0] if r else 0) or 0)
        return {"used": used, "limit": limit,
                "remaining": (limit - used) if limit > 0 else -1,
                "can_query": limit < 0 or used < limit}
    except Exception:
        return {"used": 0, "limit": limit, "remaining": -1, "can_query": True, "error": True}
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def limit_message(chk: dict) -> str:
    """한도를 넘었을 때 화면에 그대로 뜨는 문장 — 숫자는 서버 값을 쓴다(스토어 화면과 같은 원칙)."""
    lim = (chk or {}).get("limit")
    return ("플레이스 분석 일일 제한" + (f"({lim}회)" if isinstance(lim, int) and lim > 0 else "")
            + "을 초과했습니다. 내일 자정에 초기화됩니다.")


def _has_table(conn, name: str) -> bool:
    try:
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())
    except Exception:
        return False


def stats(conn=None, today: Optional[str] = None) -> dict:
    """분석기별 합계 + 직원별 플레이스 횟수. 조회 실패는 빈 dict(= 「못 쟀다」 · 0 과 다르다).

    돌려주는 것:
      by_analyzer = {"store": {total, this_month, today},
                     "place": {total, this_month, today, fails_today, fails_month, since}}
      per_user    = {user_id(str): {place_today, place_month, place_total}}
    ⚠️ 스토어 합계는 `daily_usage` 를 그대로 읽는다 — 기존 화면 숫자와 같다.
    """
    own = conn is None
    t = today or date.today().isoformat()
    m = t[:8] + "01"
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        store = None
        if _has_table(conn, "daily_usage"):
            r = conn.execute(
                "SELECT COALESCE(SUM(query_count),0) total, "
                "       COALESCE(SUM(CASE WHEN usage_date>=? THEN query_count ELSE 0 END),0) month, "
                "       COALESCE(SUM(CASE WHEN usage_date=? THEN query_count ELSE 0 END),0) day "
                "  FROM daily_usage", (m, t)).fetchone()
            store = {"total": r["total"], "this_month": r["month"], "today": r["day"]}
        r = conn.execute(
            "SELECT COALESCE(SUM(runs),0) total, "
            "       COALESCE(SUM(CASE WHEN usage_date>=? THEN runs ELSE 0 END),0) month, "
            "       COALESCE(SUM(CASE WHEN usage_date=? THEN runs ELSE 0 END),0) day, "
            "       COALESCE(SUM(CASE WHEN usage_date>=? THEN fails ELSE 0 END),0) fmonth, "
            "       COALESCE(SUM(CASE WHEN usage_date=? THEN fails ELSE 0 END),0) fday, "
            "       MIN(usage_date) since "
            "  FROM analyzer_usage WHERE analyzer='place'", (m, t, m, t)).fetchone()
        place = {"total": r["total"], "this_month": r["month"], "today": r["day"],
                 "fails_month": r["fmonth"], "fails_today": r["fday"], "since": r["since"],
                 "viewer_daily_limit": PLACE_VIEWER_DAILY_LIMIT}
        per_user = {}
        for u in conn.execute(
                "SELECT user_id, "
                "       SUM(runs) total, "
                "       SUM(CASE WHEN usage_date>=? THEN runs ELSE 0 END) month, "
                "       SUM(CASE WHEN usage_date=? THEN runs ELSE 0 END) day "
                "  FROM analyzer_usage WHERE analyzer='place' GROUP BY user_id", (m, t)).fetchall():
            per_user[str(u["user_id"])] = {"place_today": u["day"] or 0,
                                           "place_month": u["month"] or 0,
                                           "place_total": u["total"] or 0}
        return {"by_analyzer": {"store": store, "place": place}, "per_user": per_user}
    except Exception:
        return {}
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
