"""업체 상세페이지 HTML 별도 보관 — 목록 조회 느림의 원인 제거 (2026-08-30 대표 확정).

⚠️ **왜 옮기는가 — 실측으로 확정한 원인**
   `clients.detail_html` 은 업체 한 곳당 **평균 1.1MB**(714곳 = 774MB)인데,
   SQLite 는 한 행을 이어진 페이지로 저장하므로 **그 덩어리 뒤에 있는 칸을 읽으려면
   덩어리를 통째로 지나가야 한다.** 그런데 화면이 매번 쓰는 칸(`contract_stage`·
   `auto_analysis`·`track_until`·`vertical`…)이 전부 그 뒤에 있다.

   2026-08-30 서버 A/B 실측(활성 업체 703곳):
     · `id` 만               →   0 ms   (색인만 봄)
     · `id, name`            →   2 ms   (덩어리 **앞** 칸)
     · `id, contract_stage`  → 635 ms   (덩어리 **뒤** 칸) ← **300배**
   그래서 목록·대시보드·순위 화면이 다 같이 느렸다.

⚠️ **컬럼을 지우지 않는다.** SQLite 의 컬럼 삭제는 표를 통째로 다시 만드는 일이라
   26개 칸·인덱스·동시 접근을 한 번에 위험에 태운다. 대신 **값을 옆 표로 옮기고
   원래 칸은 빈 문자열로 만든다** — 그러면 그 행이 다시 쓰이면서 덩어리가 사라져
   VACUUM 전에도 즉시 빨라지고, 옛 코드 경로가 남아 있어도 깨지지 않는다.

⚠️ 읽기는 **옆 표 → 없으면 옛 칸** 순서로 본다(이관 도중에도 값이 안 사라진다).

⚠️ 표준 라이브러리만 쓴다 — 배포 회귀 게이트가 fastapi 없이 import 한다
   (`split_rule`·`tracking_eligibility`·`client_buckets`·`keyword_mute` 와 같은 이유).
"""

import logging
import zlib

logger = logging.getLogger(__name__)

# ⚠️ 압축해서 보관한다. 상세 HTML 은 같은 태그가 반복되는 문서라 10분의 1 안쪽으로 줄고,
#    줄어든 만큼 **메모리에 다른 데이터가 들어갈 자리**가 생긴다(느림의 두 번째 원인).
#    옮기기만 하면 자리만 바뀔 뿐 DB 크기는 그대로다 — 그래서 이관과 압축을 같이 한다.
#    읽을 때 bytes 면 풀고, 옛 글자 그대로면 그대로 돌려준다(형식이 섞여 있어도 안전).


def _pack(html: str):
    try:
        return zlib.compress((html or "").encode("utf-8"), 6)
    except Exception:
        return html or ""


def _unpack(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        try:
            return zlib.decompress(bytes(v)).decode("utf-8", "replace")
        except Exception:
            try:
                return bytes(v).decode("utf-8", "replace")
            except Exception:
                return ""
    return str(v)


def ensure_table(conn) -> None:
    """옆 표 보장(멱등).

    ⚠️ 호출자가 트랜잭션 안이면 여기서 commit 하지 않는다(중간 commit 이 호출자의
       쓰기 락 구간을 조용히 끝낸다 — keyword_mute 에서 한 번 정리한 규칙).
    """
    try:
        was_in_txn = bool(getattr(conn, "in_transaction", False))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_detail_html (
                client_id  INTEGER PRIMARY KEY,
                html       TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )""")
        if not was_in_txn:
            conn.commit()
    except Exception as e:
        logger.warning(f"[상세HTML] 표 보장 실패(무시): {e}")


def get_html(conn, client_id) -> str:
    """이 업체의 상세 HTML — 옆 표 우선, 없으면 옛 칸(이관 전 데이터).

    ⚠️ 실패는 빈 문자열이다. 상세 HTML 은 분석을 **풍부하게** 하는 재료일 뿐이라,
       못 읽었다고 분석 자체가 멈추면 안 된다(원래 호출부도 그렇게 쓰고 있다).
    """
    try:
        ensure_table(conn)
        r = conn.execute(
            "SELECT html FROM client_detail_html WHERE client_id=?", (client_id,)).fetchone()
        if r is not None:
            got = _unpack(r[0])
            if got.strip():
                return got
    except Exception as e:
        logger.warning(f"[상세HTML] 조회 실패(옛 칸으로 폴백) [{client_id}]: {e}")
    try:
        r = conn.execute("SELECT detail_html FROM clients WHERE id=?", (client_id,)).fetchone()
        return (r[0] if r else "") or ""
    except Exception:
        return ""


def set_html(conn, client_id, html) -> None:
    """상세 HTML 저장 — 옆 표에만 쓴다.

    ⚠️ 같은 업체의 옛 칸도 비운다. 안 비우면 새로 저장할 때마다 예전 덩어리가
       업체 표에 그대로 남아 이 차수가 없앤 느림이 되살아난다.
    """
    ensure_table(conn)
    conn.execute(
        "INSERT INTO client_detail_html(client_id, html, updated_at) "
        "VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(client_id) DO UPDATE SET html=excluded.html, updated_at=excluded.updated_at",
        (client_id, _pack(html)))
    try:
        conn.execute("UPDATE clients SET detail_html='' WHERE id=? AND COALESCE(detail_html,'') != ''",
                     (client_id,))
    except Exception as e:
        logger.warning(f"[상세HTML] 옛 칸 비우기 실패(저장은 유효) [{client_id}]: {e}")


def migrate_batch(conn, limit: int = 20) -> int:
    """옛 칸에 남은 덩어리를 옆 표로 옮긴다. 옮긴 건수를 돌려준다(0이면 끝).

    ⚠️ **한 번에 다 옮기지 않는다.** 774MB 를 한 트랜잭션으로 다시 쓰면 그동안
       DB 가 잠겨 화면이 멈춘다. 조금씩 옮기고 매번 커밋해 잠금을 짧게 끊는다.
    ⚠️ 값을 **먼저 복사하고 그 다음에 비운다** — 순서가 바뀌면 중간에 죽었을 때
       원문이 사라진다.
    """
    ensure_table(conn)
    rows = conn.execute(
        "SELECT id, detail_html FROM clients "
        "WHERE COALESCE(detail_html,'') != '' ORDER BY id LIMIT ?", (limit,)).fetchall()
    moved = 0
    for r in rows:
        cid, html = r[0], r[1]
        try:
            conn.execute(
                "INSERT INTO client_detail_html(client_id, html, updated_at) "
                "VALUES (?, ?, datetime('now','localtime')) "
                "ON CONFLICT(client_id) DO UPDATE SET html=excluded.html",
                (cid, _pack(html)))
            conn.execute("UPDATE clients SET detail_html='' WHERE id=?", (cid,))
            conn.commit()
            moved += 1
        except Exception as e:
            logger.warning(f"[상세HTML] 이관 실패(건너뜀) [{cid}]: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
    return moved


def pending_count(conn) -> int:
    """아직 옛 칸에 남아 있는 업체 수(이관 진행률 확인용)."""
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM clients WHERE COALESCE(detail_html,'') != ''").fetchone()[0]
    except Exception:
        return 0
