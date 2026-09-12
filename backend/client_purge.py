"""업체를 지울 때 함께 지워야 하는 자식 — **한 곳에서만 정한다.**

⚠️ **이 파일이 생긴 경위 (2026-09-11 실측)**
   업체 하드삭제 경로가 **5개**였고 지우는 자식이 제각각이었다.
   ```
   client_dashboard.py:373   분석·순위이력  (1회성 이관)
   client_dashboard.py:416   분석·순위이력  (1회성 이관)
   client_dashboard.py:1283  분석·순위이력·보고서   ← 가장 완전(신고 #259 로 보고서 추가)
   client_dashboard.py:2206  분석            ← 순위이력 빠짐
   clients.py:526            **없음**        ← clients 행만 지운다
   ```
   `client_analyses`·`client_rank_history`·`client_keyword_product` 에는
   `ON DELETE CASCADE` 가 걸려 있지만 **CASCADE 는 그 연결에 `PRAGMA foreign_keys=ON`
   이 켜져 있을 때만 돈다.** SQLite 기본값은 꺼짐이다.
   `database.py:_get_conn`·`client_dashboard.py:_get_conn` 은 켜는데
   **`clients.py:get_db_connection` 만 안 켠다** — 그 경로로 지운 업체는
   자식이 통째로 고아가 된다(진단이 센 「고아 순위행」의 출처).

   ⭐ **교훈 — 같은 일을 하는 코드가 몇 개인지 먼저 센다.**
      오늘만 세 번째다: 백업 경로 2개(스케줄·기동) · 큐 되먹임 차단 2자리 ·
      그리고 이 삭제 경로 5개. 한 곳만 고치면 나머지가 같은 사고를 낸다.

⚠️ **왜 CASCADE 에 기대지 않고 명시적으로 지우는가**
   연결마다 PRAGMA 가 다른 것이 사고의 원인이었다. 명시적 삭제는 PRAGMA 와 무관하게
   같은 결과를 낸다. 또 `reports` 는 CASCADE 가 아예 없어 어차피 명시 삭제가 필요하다
   (신고 #259 — 보고서가 남아 있으면 FK 오류로 업체 삭제 자체가 막혔다).

표준 라이브러리만 쓴다 — 배포 게이트 환경에 fastapi 가 없다.
"""

import logging

logger = logging.getLogger(__name__)

# 업체와 생사를 같이하는 자식 표. (표 이름, 업체를 가리키는 칸)
# ⚠️ 순서가 있다 — `clients` 를 지우기 **전에** 전부 지워야 FK 오류가 안 난다.
# ⚠️ 여기에 없는 것은 일부러 뺀 것이다:
#    · api_usage_logs·report_owner_sync_log — 기록(로그)이라 업체가 없어져도 남긴다
#    · handover_transfer_request — 인수인계 이력. 업체 삭제로 지울 성격이 아니다
CHILD_TABLES = (
    ("client_analyses", "client_id"),
    ("client_rank_history", "client_id"),
    ("client_keyword_product", "client_id"),
    ("reports", "client_id"),
    ("rank_link", "client_id"),
)


def purge_client_children(conn, client_id) -> dict:
    """업체의 자식 행을 전부 지운다. `clients` 자체는 **건드리지 않는다**(호출부 몫).

    돌려주는 값: {표이름: 지운 행 수}. 커밋은 호출부가 한다(트랜잭션을 쪼개지 않기 위해).
    한 표에서 실패해도 나머지는 계속 지운다 — 일부만 남는 것보다 낫다.
    """
    out = {}
    for table, col in CHILD_TABLES:
        try:
            cur = conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (client_id,))
            n = cur.rowcount or 0
            if n:
                out[table] = n
        except Exception as e:
            # 표가 아직 없을 수 있다(신설 직후·구버전 DB). 그건 지울 것이 없다는 뜻이다.
            msg = str(e)
            if "no such table" not in msg.lower():
                logger.warning(f"[purge] {table} 정리 실패(계속 진행): {msg[:90]}")
    return out


def orphan_counts(conn) -> dict:
    """부모가 사라진 자식 행 수 — 읽기 전용. 정리가 필요한지 판단용."""
    out = {}
    for table, col in CHILD_TABLES:
        try:
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} "
                f" WHERE {col} IS NOT NULL AND {col} NOT IN (SELECT id FROM clients)"
            ).fetchone()[0]
            if n:
                out[table] = n
        except Exception:
            pass
    return out


def prune_orphans(conn) -> dict:
    """부모가 이미 사라진 자식 행을 청소한다. 돌려주는 값: {표이름: 지운 행 수}.

    ⚠️ 과거에 새던 경로가 남긴 것을 치우는 용도다. 새로 새는 것은 위
       `purge_client_children` 을 삭제 경로마다 쓰는 것으로 막는다.
    """
    out = {}
    for table, col in CHILD_TABLES:
        try:
            cur = conn.execute(
                f"DELETE FROM {table} "
                f" WHERE {col} IS NOT NULL AND {col} NOT IN (SELECT id FROM clients)"
            )
            n = cur.rowcount or 0
            if n:
                out[table] = n
        except Exception as e:
            msg = str(e)
            if "no such table" not in msg.lower():
                logger.warning(f"[purge] {table} 고아 정리 실패(계속 진행): {msg[:90]}")
    return out
