"""수집이 멈춘 것을 **서버가 스스로 알아챈다** (대표 확정 2026-09-10).

⚠️ 이 파일이 생긴 이유 — **하루가 통째로 0건이 됐는데 아무도 몰랐다.**
   2026-09-09 캡차 → 2026-09-10 수집 0건. 그런데 서비스는 멀쩡히 돌고,
   화면도 어제 순위를 그대로 보여 준다. 대표가 팝업을 열어 보기 전까지
   **아무 데서도 「멈췄다」는 신호가 나오지 않았다.**

   ⇒ 매시간 「마지막 업로드가 언제였나」를 재서, 너무 오래 조용하면 알린다.

⚠️ **요청이 아니라 업로드로 잰다.** `/api/collector/health` 같은 요청은 수집을 꺼 둔
   기계도 계속 보낸다 — 그걸로 판정하면 「살아 있다」는 착각을 한다(2026-09-10 실수).
   실제로 값이 올라온 것(`collected_serp.created_at`)만 본다.

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다
   (sbiz_health·tracking_eligibility·split_rule 과 같은 이유).

⚠️ **어떤 실패도 밖으로 내보내지 않는다.** 알림이 안 가는 것보다 서버가 멈추는 게 훨씬 나쁘다.
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


def _int_env(name: str, default: int) -> int:
    """환경변수로 조절하되, 값이 이상하면 기본값으로 돌아간다."""
    try:
        v = int(str(os.getenv(name, "")).strip())
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


# 몇 시간 조용하면 「멈췄다」로 보나.
# ⚠️ 5시간으로 잡은 근거: 수집은 시간대별로 24시간 나눠 도므로 정상이면 간격이 1~2시간이다.
#    캡차를 만나면 6시간 쉰다 — 그 쉼도 알림 대상이 맞다(대표가 알아야 하는 상태다).
#    다만 새벽에 문자가 가지 않도록 **부르는 시각을 낮으로 제한**한다(scheduler 쪽).
ALERT_GAP_HOURS = _int_env("COLLECT_ALERT_GAP_HOURS", 5)
# 같은 사고로 몇 시간에 한 번까지만 알리나(문자 도배 방지).
COOLDOWN_HOURS = _int_env("COLLECT_ALERT_COOLDOWN_HOURS", 6)

STATE_OK = "ok"
STATE_QUIET = "quiet"
STATE_UNKNOWN = "unknown"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn) -> None:
    """멱등. 진행 중인 트랜잭션 안에서는 commit 하지 않는다(sbiz_health 와 같은 이유)."""
    try:
        in_tx = conn.in_transaction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collect_watch(
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                gap_hours  REAL,
                state      TEXT NOT NULL,      -- ok / quiet / unknown
                notified   INTEGER DEFAULT 0,  -- 이 판정으로 실제 알림을 보냈나
                note       TEXT DEFAULT ''
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_collect_watch_at ON collect_watch(checked_at)")
        if not in_tx:
            conn.commit()
    except Exception:
        pass


def last_upload_at(conn) -> Optional[str]:
    """마지막으로 값이 **실제로 올라온** 시각(KST 문자열). 없으면 None.

    ⚠️ `collected_serp` 는 (키워드, 날짜) 유일 색인이라 재수집이 UPDATE 로 들어가는데,
       그 UPDATE 가 `created_at` 을 지금 시각으로 다시 쓴다(collector.upload_serp).
       그래서 MAX(created_at) 이 「마지막 업로드」로 정확하다.
    """
    try:
        r = conn.execute("SELECT MAX(created_at) m FROM collected_serp").fetchone()
        return r["m"] if r and r["m"] else None
    except Exception:
        return None


def evaluate(conn) -> dict:
    """지금 상태를 판정한다. DB 를 고치지 않는다(읽기 전용)."""
    last = last_upload_at(conn)
    if not last:
        # 한 번도 올라온 적이 없다 = 새 서버이거나 표가 비었다. 사고로 단정하지 않는다.
        return {"last_upload": None, "gap_hours": None, "state": STATE_UNKNOWN}
    try:
        r = conn.execute(
            "SELECT (julianday('now','localtime') - julianday(?)) * 24 g", (last,)).fetchone()
        gap = r["g"] if r else None
    except Exception:
        gap = None
    if gap is None:
        return {"last_upload": last, "gap_hours": None, "state": STATE_UNKNOWN}
    gap = round(float(gap), 2)
    # ⚠️ 시계가 어긋나 음수가 나올 수 있다 — 그때는 「방금 올라왔다」로 본다(알림 금지).
    if gap < 0:
        gap = 0.0
    return {"last_upload": last, "gap_hours": gap,
            "state": STATE_QUIET if gap >= ALERT_GAP_HOURS else STATE_OK}


def _last_row(conn):
    try:
        return conn.execute(
            "SELECT * FROM collect_watch ORDER BY id DESC LIMIT 1").fetchone()
    except Exception:
        return None


def _hours_since(conn, ts: str) -> Optional[float]:
    try:
        r = conn.execute(
            "SELECT (julianday('now','localtime') - julianday(?)) * 24 g", (ts,)).fetchone()
        return float(r["g"]) if r and r["g"] is not None else None
    except Exception:
        return None


def decide_notice(conn, state: str) -> Optional[str]:
    """이번 판정으로 **무엇을 알릴 것인가**. 알릴 게 없으면 None.

    규칙 세 가지 — 셋 다 「사람이 문자를 받고 나서 짜증 내지 않을 것」이 기준이다.
      ① 조용해졌다(ok/처음 → quiet)   : 알린다
      ② 계속 조용하다(quiet → quiet)  : 쿨다운(기본 6시간) 지났을 때만 다시 알린다
      ③ 돌아왔다(quiet → ok)          : 한 번 알린다. 이게 없으면 「고쳐졌는지」를 또 물어야 한다
    unknown 은 아무것도 알리지 않는다 — 「데이터가 없다」와 「멈췄다」는 다른 축이다.
    """
    if state == STATE_UNKNOWN:
        return None
    prev = _last_row(conn)
    prev_state = prev["state"] if prev else None
    if state == STATE_QUIET:
        if prev_state != STATE_QUIET:
            return "quiet"
        # 이미 조용한 상태였다 — 마지막으로 **알림을 보낸** 시각 기준으로 쿨다운을 잰다.
        try:
            # ⚠️ **실제로 나간 것만** 쿨다운을 건다.
            #    「수신 번호가 없어 못 보냄(nosend)」을 보낸 것으로 세면, 번호를 나중에 넣어도
            #    쿨다운이 남아 그날은 영영 안 온다(2026-09-10 실측으로 드러났다).
            #    안 나간 것은 도배가 될 수 없다 — 문자가 없으니까.
            r = conn.execute(
                "SELECT MAX(checked_at) m FROM collect_watch "
                " WHERE notified=1 AND COALESCE(note,'') NOT LIKE '%nosend%'").fetchone()
            last_notified = r["m"] if r else None
        except Exception:
            last_notified = None
        if not last_notified:
            return "quiet"
        h = _hours_since(conn, last_notified)
        return "quiet" if (h is None or h >= COOLDOWN_HOURS) else None
    # state == ok
    return "recovered" if prev_state == STATE_QUIET else None


def _text(kind: str, gap: Optional[float]) -> str:
    """문자 본문.

    ⚠️ **SMS 는 90바이트(한글 약 45자)** 다. 넘치면 뒤가 잘려 「무엇을 하라」가 사라진다.
       처음 쓴 문장이 100바이트였고 시험이 잡았다 — 길이는 시험이 지킨다(아래 ② 항목).
    """
    if kind == "recovered":
        return "[로직분석] 순위 수집이 다시 올라오고 있습니다."   # 65바이트
    hours = int(gap) if gap else ALERT_GAP_HOURS
    return f"[로직분석] 순위 수집 {hours}시간째 멈춤. 맥미니 확인 바랍니다."   # 78바이트


def record(conn, state: str, gap: Optional[float], notified: bool,
           note: str = "", commit: bool = True) -> None:
    """한 번의 판정을 남긴다.

    ⚠️ **`if not conn.in_transaction: commit()` 을 쓰면 안 된다.** INSERT 직후에는
       sqlite3 가 암묵 트랜잭션을 열어 둬 `in_transaction` 이 항상 True 다 —
       그래서 commit 이 통째로 건너뛰어지고 `conn.close()` 에서 롤백된다.
       그러면 「직전 상태」를 영영 못 읽어 **매시간 같은 문자가 나간다**(시험이 잡았다).
       연결을 남이 쥐고 있으면 `commit=False` 로 불러 그쪽이 커밋하게 한다.
    """
    try:
        ensure_table(conn)
        conn.execute(
            "INSERT INTO collect_watch(checked_at, gap_hours, state, notified, note) "
            "VALUES(?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), gap, state,
             1 if notified else 0, (note or "")[:120]))
        if commit:
            conn.commit()
    except Exception:
        pass


def run_check(send=None, conn=None) -> dict:
    """매시간 부르는 본체. `send(text) -> bool` 을 주면 그것으로 알린다(시험용 주입구).

    돌려주는 것: {state, gap_hours, last_upload, notice, sent}
    ⚠️ 어떤 실패도 밖으로 내보내지 않는다.
    """
    own = conn is None
    out = {"state": STATE_UNKNOWN, "gap_hours": None, "last_upload": None,
           "notice": None, "sent": False}
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        ev = evaluate(conn)
        out.update(ev)
        notice = decide_notice(conn, ev["state"])
        out["notice"] = notice
        sent = False
        if notice and send is not None:
            try:
                sent = bool(send(_text(notice, ev.get("gap_hours"))))
            except Exception:
                sent = False
        out["sent"] = sent
        # ⚠️ **실제로 나간 것만** notified 로 남긴다.
        #    처음엔 「보내려고 했으면」으로 적었는데 그게 틀렸다 — 수신 번호가 없어 못 보낸 판정이
        #    쿨다운을 걸어, 번호를 넣은 뒤에도 그날은 문자가 안 오는 상태가 됐다(2026-09-10).
        #    못 나간 것은 도배가 될 수 없다(문자가 없으니까). 사정은 note 에 남긴다.
        record(conn, ev["state"], ev.get("gap_hours"), bool(notice) and sent,
               note=("" if not notice else f"{notice}/{'sent' if sent else 'nosend'}"),
               commit=own)   # 남의 연결이면 커밋은 그쪽 몫이다
        return out
    except Exception:
        return out
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def summary(conn=None) -> dict:
    """화면·진단이 읽는 요약. 조회 실패는 빈 dict."""
    own = conn is None
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        ev = evaluate(conn)
        r = conn.execute(
            "SELECT MAX(checked_at) m FROM collect_watch WHERE notified=1").fetchone()
        ev["last_notified"] = r["m"] if r else None
        r = conn.execute(
            "SELECT COUNT(*) n FROM collect_watch "
            " WHERE state=? AND checked_at >= datetime('now','localtime','-7 day')",
            (STATE_QUIET,)).fetchone()
        ev["quiet_checks_7d"] = (r["n"] or 0) if r else 0
        ev["alert_gap_hours"] = ALERT_GAP_HOURS
        return ev
    except Exception:
        return {}
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
