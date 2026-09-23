"""수집기가 서버 명령으로 올려 보내는 로그·진단 파일 (v1.27.0 · 대표 확정 2026-09-23)

왜 — 원인을 볼 때마다 대표가 노트북 앞에서 팝업 로그를 캡처하거나 진단 파일을 내려받아 보내 줘야 했다.
      서버 설정(`collector_settings.COMMANDS`)에 `uploadLogs`·`uploadDiag` 명령을 넣고 배포하면,
      다음 신호(5분 안)에 수집기가 스스로 올린다.

⚠️ 기계별·종류별 **최근 5건만** 둔다(쌓이지 않게). 한 건 250KB 까지.
⚠️ 로그에는 검색어가 들어 있다 — 이 표의 **본문을 공개 저장소의 진단 워크플로 로그에 찍지 말 것**
   (건수·크기·시각만). 읽는 곳은 관리자 전용 경로(`GET /api/collector/reports`) 하나다.
⚠️ stdlib 만 쓴다(배포 게이트에 fastapi 가 없다).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

KINDS = ("logs", "diag")
KEEP_PER_KIND = 5
MAX_BYTES = 250_000

DDL = """
CREATE TABLE IF NOT EXISTS collector_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    kind        TEXT NOT NULL,
    body        TEXT NOT NULL,
    bytes       INTEGER DEFAULT 0,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collector_reports_inst ON collector_reports(instance_id, kind, id);
"""


def ensure_table(conn) -> None:
    try:
        conn.executescript(DDL)
        conn.commit()
    except Exception:
        pass


def save(conn, instance_id: Any, kind: Any, text: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """한 건 저장 · 오래된 것 정리. 잘못된 요청이면 {"saved": False, "reason": …}."""
    iid = str(instance_id or "").strip()[:64]
    k = str(kind or "").strip()
    if not iid:
        return {"saved": False, "reason": "instanceId 없음"}
    if k not in KINDS:
        return {"saved": False, "reason": "모르는 종류"}
    body = str(text or "")
    raw = body.encode("utf-8")
    if len(raw) > MAX_BYTES:
        body = raw[:MAX_BYTES].decode("utf-8", errors="ignore")
    ensure_table(conn)
    at = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO collector_reports(instance_id, kind, body, bytes, at) VALUES(?,?,?,?,?)",
                 (iid, k, body, len(body.encode("utf-8")), at))
    conn.execute("""DELETE FROM collector_reports WHERE instance_id=? AND kind=? AND id NOT IN (
                        SELECT id FROM collector_reports WHERE instance_id=? AND kind=? ORDER BY id DESC LIMIT ?)""",
                 (iid, k, iid, k, KEEP_PER_KIND))
    conn.commit()
    return {"saved": True, "at": at, "bytes": len(body.encode("utf-8"))}


def latest(conn, instance_id: Optional[str] = None, kind: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """관리자 조회용. 실패는 빈 목록이 아니라 예외를 올린다(호출자가 「못 읽음」으로 가른다)."""
    ensure_table(conn)
    q = "SELECT id, instance_id, kind, body, bytes, at FROM collector_reports WHERE 1=1"
    args: List[Any] = []
    if instance_id:
        q += " AND instance_id=?"
        args.append(str(instance_id))
    if kind:
        q += " AND kind=?"
        args.append(str(kind))
    q += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(50, int(limit))))
    cur = conn.execute(q, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
