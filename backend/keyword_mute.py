"""업체×키워드 「그만 재기」 억제 목록 — 판정·저장 단일 소스 (2026-08-29 대표 확정).

⚠️ 이 표가 생긴 이유 — 키워드를 「지우는」 길이 없었다.
   업체 키워드는 두 갈래(대표 키워드 main_keywords ∪ 분석 이력 client_analyses)로
   수집·기록 대상이 되는데, 대표 키워드에서 이름을 빼도 **분석 이력에 남아 있으면
   수집이 계속 돈다.** 이력을 지우면 순위 기록·분석 기록이 사라져 되돌릴 수 없다.
   → 지우지 않고 「이 업체는 이 키워드를 그만 잰다」 표시만 남긴다(억제).
     · 수집 유니버스·순위 기록·나눠 적기·화면 보드가 전부 이 표를 보고 뺀다
     · 기록은 그대로 → 같은 키워드를 다시 등록하면(억제 해제) 이력이 그대로 복귀

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다
   (split_rule · tracking_eligibility · client_buckets 와 같은 이유).

⚠️ 키워드 비교는 **strip 한 원문 그대로**다. main_keywords·tracked_keywords·유니버스가
   전부 strip 원문을 쓰므로 여기만 정규화(공백 제거 등)를 더 하면 서로 어긋난다.
"""


def ensure_mute_table(conn) -> None:
    """억제 표 보장(멱등).

    ⚠️ 호출자가 트랜잭션(BEGIN IMMEDIATE) 안에 있으면 여기서 commit 하지 않는다 —
       중간 commit 은 호출자의 락 구간을 조용히 끝내 lost update 방지를 무력화한다.
    """
    try:
        was_in_txn = bool(getattr(conn, "in_transaction", False))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_keyword_mute (
                client_id INTEGER NOT NULL,
                keyword   TEXT NOT NULL,
                muted_by  INTEGER DEFAULT 0,
                muted_at  TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (client_id, keyword)
            )""")
        if not was_in_txn:
            conn.commit()
    except Exception:
        pass


def muted_map(conn) -> dict:
    """{client_id: set(keyword)} — 조회 실패 시 빈 dict(=아무것도 안 뺀다).

    ⚠️ 실패를 '전부 억제'로 읽으면 수집이 통째로 멈춘다. 빈 dict 폴백이 안전한 방향.
    """
    try:
        ensure_mute_table(conn)
        out = {}
        for r in conn.execute("SELECT client_id, keyword FROM client_keyword_mute"):
            out.setdefault(r[0], set()).add((r[1] or "").strip())
        return out
    except Exception:
        return {}


def muted_set(conn, client_id) -> set:
    try:
        ensure_mute_table(conn)
        return {(r[0] or "").strip() for r in conn.execute(
            "SELECT keyword FROM client_keyword_mute WHERE client_id=?", (client_id,))}
    except Exception:
        return set()


def mute(conn, client_id, keyword, by=0) -> None:
    ensure_mute_table(conn)
    conn.execute("INSERT OR REPLACE INTO client_keyword_mute(client_id, keyword, muted_by) "
                 "VALUES (?, ?, ?)", (client_id, (keyword or "").strip(), by))


def unmute(conn, client_id, keyword) -> None:
    """재등록 = 복귀. 표에 없어도 조용히 성공(멱등)."""
    ensure_mute_table(conn)
    conn.execute("DELETE FROM client_keyword_mute WHERE client_id=? AND keyword=?",
                 (client_id, (keyword or "").strip()))
