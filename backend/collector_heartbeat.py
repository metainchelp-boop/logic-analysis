"""수집기 살아있음 신호(heartbeat) — v1.21.0 (대표 확정 2026-09-22 · 수집기 자체 개발 1차)

왜 만들었나
  2번 설정 노트북이 9/21 07:29 부터 서버에 요청을 **한 건도** 안 보냈다. 일시정지·캡차 쉼·크롬 종료·
  알람 소실 — 어느 것이든 서버 쪽 신호는 똑같이 「0건」이라 **원인을 가를 수 없었다**(대표 「원인을 몰라」).
  ⇒ 확장이 5분마다 **멈춰 있어도** 자기 상태를 보낸다. 서버는 기계별 마지막 신호와 그때의 상태를 갖는다.
  ⚠️ 신호가 끊긴 기계 = 「크롬/확장이 아예 안 돈다」, 신호는 오는데 수집 0 = 「멈춘 이유가 상태에 적혀 있다」.

⚠️ stdlib 만 쓴다 — 배포 게이트에 fastapi 가 없어 이 모듈은 가짜 DB 로 직접 시험한다.
⚠️ 개인정보 없음 — 기계 식별은 확장이 스스로 만든 무작위 id, IP 는 받지도 저장하지도 않는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

STALE_MINUTES = 15          # 5분 주기 신호가 이만큼 안 오면 「끊김」
HEARTBEAT_PERIOD_MIN = 5    # 확장 알람 주기와 같은 값(문서용 · 판정엔 STALE_MINUTES 만 쓴다)

DDL = """
CREATE TABLE IF NOT EXISTS collector_heartbeat (
    instance_id      TEXT PRIMARY KEY,
    worker_no        INTEGER DEFAULT 1,
    worker_count     INTEGER DEFAULT 1,
    ext_version      TEXT DEFAULT '',
    chrome_version   TEXT DEFAULT '',
    reason           TEXT DEFAULT '',
    paused_local     INTEGER DEFAULT 0,
    paused_screen    INTEGER DEFAULT 0,
    blocked_until    TEXT DEFAULT '',
    slow_until       TEXT DEFAULT '',
    running          INTEGER DEFAULT 0,
    last_finished_at TEXT DEFAULT '',
    day_done         INTEGER DEFAULT 0,
    day_total        INTEGER DEFAULT 0,
    last_error       TEXT DEFAULT '',
    alarms           TEXT DEFAULT '',
    first_seen       TEXT,
    last_seen        TEXT,
    seen_count       INTEGER DEFAULT 0
);
"""

_FMT = "%Y-%m-%d %H:%M:%S"


def _now_str(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime(_FMT)


def ensure_table(conn) -> None:
    """멱등. 실패해도 예외를 밖으로 내지 않는다(수집 경로가 이 표 때문에 죽으면 안 된다)."""
    try:
        conn.executescript(DDL)
        conn.commit()
    except Exception:
        pass
    # 📤 4차(코덱스 이식) — 미전송 보관함 요약 칸. 옛 표에도 ALTER 로 더한다(멱등 · 실패 무시).
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(collector_heartbeat)").fetchall()}
        for name, ddl in (("upload_summary_json", "TEXT"), ("upload_summary_at", "INTEGER")):
            if name not in cols:
                conn.execute(f"ALTER TABLE collector_heartbeat ADD COLUMN {name} {ddl}")
        conn.commit()
    except Exception:
        pass


def _ms_to_local(v: Any) -> str:
    """확장이 보내는 epoch ms(또는 ISO 문자열) → 'YYYY-MM-DD HH:MM:SS'. 0·빈 값은 ''."""
    if v in (None, "", 0, "0"):
        return ""
    try:
        n = float(v)
        if n > 1e11:          # ms 단위
            return datetime.fromtimestamp(n / 1000).strftime(_FMT)
        if n > 0:             # s 단위
            return datetime.fromtimestamp(n).strftime(_FMT)
        return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().strftime(_FMT)
    except Exception:
        return s[:19]


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def record(conn, payload: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """신호 1건을 기계(instance_id)별 최신 행으로 갱신한다(upsert). 반환 = 저장한 값 요약.

    instance_id 가 비면 저장하지 않고 {"skipped": True} — 옛 확장(1.20 이하)은 이 경로를 부르지 않으므로
    빈 id 는 잘못된 호출이다. 조용히 무시한다.
    """
    p = payload or {}
    iid = str(p.get("instanceId") or p.get("instance_id") or "").strip()[:64]
    if not iid:
        return {"skipped": True}
    ensure_table(conn)
    ts = _now_str(now)
    alarms = p.get("alarms")
    if isinstance(alarms, (list, tuple)):
        alarms_s = ",".join(str(a) for a in alarms)[:200]
    else:
        alarms_s = str(alarms or "")[:200]
    row = {
        "instance_id": iid,
        "worker_no": max(1, _i(p.get("workerNo"), 1)),
        "worker_count": max(1, _i(p.get("workerCount"), 1)),
        "ext_version": str(p.get("extVersion") or "")[:20],
        "chrome_version": str(p.get("chromeVersion") or "")[:30],
        "reason": str(p.get("reason") or "")[:20],
        "paused_local": 1 if p.get("pausedByLocal") else 0,
        "paused_screen": 1 if p.get("pausedByScreen") else 0,
        "blocked_until": _ms_to_local(p.get("blockedUntil")),
        "slow_until": _ms_to_local(p.get("slowUntil")),
        "running": 1 if p.get("running") else 0,
        "last_finished_at": _ms_to_local(p.get("lastFinishedAt")),
        "day_done": _i(p.get("dayDone")),
        "day_total": _i(p.get("dayTotal")),
        "last_error": str(p.get("lastError") or "")[:200],
        "alarms": alarms_s,
        "last_seen": ts,
    }
    # 📤 미전송 보관함 요약 — 형식이 맞을 때만 저장한다(어긋나면 INVALID 표식 — 0 이 아니라 「못 쟀다」).
    us = p.get("uploadSummary")
    row["upload_summary_json"], row["upload_summary_at"] = None, None
    if us is not None:
        _now_epoch = int((now or datetime.now()).timestamp())
        try:
            from collector_telemetry import validate_upload_summary
            row["upload_summary_json"] = json.dumps(validate_upload_summary(us, now=_now_epoch), ensure_ascii=False)
        except Exception:
            row["upload_summary_json"] = "INVALID"
        row["upload_summary_at"] = _now_epoch
    conn.execute(
        """INSERT INTO collector_heartbeat(instance_id, worker_no, worker_count, ext_version, chrome_version,
               reason, paused_local, paused_screen, blocked_until, slow_until, running, last_finished_at,
               day_done, day_total, last_error, alarms, first_seen, last_seen, seen_count)
           VALUES(:instance_id, :worker_no, :worker_count, :ext_version, :chrome_version,
               :reason, :paused_local, :paused_screen, :blocked_until, :slow_until, :running, :last_finished_at,
               :day_done, :day_total, :last_error, :alarms, :last_seen, :last_seen, 1)
           ON CONFLICT(instance_id) DO UPDATE SET
               worker_no=excluded.worker_no, worker_count=excluded.worker_count,
               ext_version=excluded.ext_version, chrome_version=excluded.chrome_version,
               reason=excluded.reason, paused_local=excluded.paused_local, paused_screen=excluded.paused_screen,
               blocked_until=excluded.blocked_until, slow_until=excluded.slow_until, running=excluded.running,
               last_finished_at=excluded.last_finished_at, day_done=excluded.day_done, day_total=excluded.day_total,
               last_error=excluded.last_error, alarms=excluded.alarms,
               last_seen=excluded.last_seen, seen_count=collector_heartbeat.seen_count+1""",
        row)
    if row["upload_summary_at"] is not None:
        try:
            conn.execute("UPDATE collector_heartbeat SET upload_summary_json=?, upload_summary_at=? WHERE instance_id=?",
                         (row["upload_summary_json"], row["upload_summary_at"], iid))
        except Exception:
            pass   # 칸이 없는 옛 표 — 신호 자체는 이미 저장됐다
    conn.commit()
    return row


def status_text(r: Dict[str, Any], now: Optional[datetime] = None) -> str:
    """사람이 읽는 한 줄 — 멈춘 이유를 **우선순위대로** 하나만 말한다(끊김 > 일시정지 > 캡차 쉼 > 화면 끔 > 수집 중 > 대기)."""
    n = now or datetime.now()
    try:
        seen = datetime.strptime(str(r.get("last_seen") or ""), _FMT)
        if n - seen > timedelta(minutes=STALE_MINUTES):
            mins = int((n - seen).total_seconds() // 60)
            return f"⛔ 신호 끊김 {mins}분 — 크롬·확장이 안 돈다"
    except ValueError:
        return "⛔ 신호 없음"
    if r.get("paused_local"):
        return "⏸ 일시정지(사람이 팝업에서 누름)"
    bu = str(r.get("blocked_until") or "")
    if bu and bu > _now_str(n):
        return f"🧱 캡차 쉼 — {bu[11:16]} 이후 재개"
    if r.get("paused_screen"):
        return "🛑 화면에서 꺼 둠"
    base = "▶ 수집 중" if r.get("running") else "대기(정상)"
    us = r.get("uploadSummary")
    if isinstance(us, dict) and us.get("count"):
        base += f" · 📤 미전송 {us['count']}건" + (f"(검토 필요 {us['reviewRequiredCount']})" if us.get("reviewRequiredCount") else "")
    return base


def machines(conn, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """기계 목록 — 화면·진단이 읽는다. 조회 실패는 빈 목록(0 이 아니라 「못 쟀다」는 호출자가 가른다)."""
    try:
        ensure_table(conn)
        cur = conn.execute("SELECT * FROM collector_heartbeat ORDER BY worker_no, last_seen DESC")
        cols = [d[0] for d in cur.description]
        out = []
        n = now or datetime.now()
        for rec in cur.fetchall():
            r = dict(zip(cols, rec))
            try:
                seen = datetime.strptime(str(r.get("last_seen") or ""), _FMT)
                r["minutes_since"] = int((n - seen).total_seconds() // 60)
            except ValueError:
                r["minutes_since"] = None
            r["stale"] = r["minutes_since"] is None or r["minutes_since"] > STALE_MINUTES
            # 📤 미전송 보관함 요약(4차) — 없음/손상은 0 이 아니라 UNREPORTED/INVALID
            try:
                from collector_telemetry import reported_upload_summary
                r["uploadSummary"], r["uploadSummaryStatus"] = reported_upload_summary(
                    r.get("upload_summary_json"), r.get("upload_summary_at"), now=int(n.timestamp()))
            except Exception:
                r["uploadSummary"], r["uploadSummaryStatus"] = None, "INVALID"
            r["status"] = status_text(r, n)
            r["machine"] = f"{r.get('worker_no', 1)}/{r.get('worker_count', 1)}"
            out.append(r)
        return out
    except Exception:
        return []


def summary_line(rows: List[Dict[str, Any]]) -> str:
    """로그·진단용 한 줄. 예: '기계 2대 — 1/2 대기(정상) · 2/2 ⛔ 신호 끊김 40분'"""
    if not rows:
        return "기계 신호 없음(v1.21.0 이상 확장이 아직 보고하지 않음)"
    return f"기계 {len(rows)}대 — " + " · ".join(f"{r['machine']} {r['status']}" for r in rows)
