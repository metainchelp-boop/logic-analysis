"""영업 자료 인계 보관소 — 보고서가 받아 둔 자료를 제안서에 넘긴다 (2026-09-15).

⚠️ **왜 이 표가 필요한가**
   로직분석 보고서와 맞춤제안서는 **서로의 결과를 쓰지 않고**, 같은 서버에 **같은 것을
   각자** 물어본다(검색량·상품 목록·데이터랩). 검색량·상품 목록에는 캐시가 없어
   **두 번 그대로 외부로 나간다.** 보고서가 받아 둔 것을 제안서가 그대로 쓰면
   기다림이 사라지고 네이버 호출도 절반이 된다.

⚠️ **왜 메모리가 아니라 DB 인가 — 워커가 5개다**
   배포는 `backend/Dockerfile`(uvicorn `--workers 5`)을 쓴다. 파이썬 딕셔너리에 담으면
   **보관한 워커와 꺼내는 워커가 다를 수 있어** 태반이 「없음」으로 떨어진다.
   눈에 잘 안 띄는 고장이라(가끔 되고 가끔 안 됨) 처음부터 DB 에 둔다.

⚠️ **오래 두지 않는다**
   영업 자료 한 번 만드는 동안만 살면 된다. `TTL_SECONDS` 가 지나면 읽을 때 무효로
   판정하고, 꺼낼 때마다 지난 것을 함께 치운다(따로 도는 청소 잡을 만들지 않는다).

⚠️ **의존성 없음(표준 라이브러리만)** — 배포 회귀 게이트가 fastapi 없이 import 한다
   (split_rule · keyword_mute · tracking_eligibility · db_backup 과 같은 이유).
"""

import json
import os
import secrets
import sqlite3
import time

#: 인계 자료의 수명(초). 영업 자료 한 번 만드는 시간이면 충분하다.
TTL_SECONDS = 30 * 60

#: 한 건의 최대 크기(바이트). 상품 목록이 커도 이 선을 넘지 않는다.
#: ⚠️ 넘으면 **보관하지 않고 그냥 실패시킨다** — 잘라서 넣으면 제안서가 반쪽 자료로
#:    조용히 그럴듯한 장표를 그린다. 그게 빈 장표보다 나쁘다.
MAX_BYTES = 2 * 1024 * 1024

_DDL = """
CREATE TABLE IF NOT EXISTS sales_bundle (
    key         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    created_by  INTEGER,
    created_at  INTEGER NOT NULL
)
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    """표를 보장한다. 여러 워커가 동시에 불러도 안전하다(IF NOT EXISTS)."""
    conn.execute(_DDL)


def new_key() -> str:
    """추측할 수 없는 인계 키. 주소에 실려 다니므로 넉넉히 길게 잡는다."""
    return secrets.token_urlsafe(24)


def put(conn: sqlite3.Connection, payload: dict, user_id=None) -> str:
    """자료를 보관하고 키를 돌려준다.

    너무 크면 ``ValueError`` — 부르는 쪽이 「인계 없이 평소대로」로 떨어지게 한다.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    size = len(body.encode("utf-8"))
    if size > MAX_BYTES:
        raise ValueError(f"인계 자료가 너무 큽니다({size} > {MAX_BYTES})")
    ensure_table(conn)
    key = new_key()
    conn.execute(
        "INSERT INTO sales_bundle (key, payload, created_by, created_at) VALUES (?, ?, ?, ?)",
        (key, body, user_id, int(time.time())),
    )
    return key


def take(conn: sqlite3.Connection, key: str, now: int = None) -> dict:
    """자료를 꺼낸다. 없거나 수명이 지났으면 ``None``.

    ⚠️ **한 번 꺼내면 지운다.** 제안서가 한 번 받아 가면 더 쓸 일이 없고,
       주소가 남의 눈에 띄어도 두 번 열리지 않는다.
    ⚠️ 꺼낼 때 **지난 것들을 함께 치운다** — 청소 잡을 따로 돌리지 않기 위해서다.
    """
    if not key:
        return None
    now = int(time.time()) if now is None else int(now)
    ensure_table(conn)
    conn.execute("DELETE FROM sales_bundle WHERE created_at < ?", (now - TTL_SECONDS,))
    row = conn.execute(
        "SELECT payload, created_at FROM sales_bundle WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    payload, created_at = row[0], row[1]
    conn.execute("DELETE FROM sales_bundle WHERE key = ?", (key,))
    if int(created_at) < now - TTL_SECONDS:
        return None            # 방금 지웠으니 되돌아오지 않는다
    try:
        return json.loads(payload)
    except Exception:
        return None


def db_path() -> str:
    """수집·순위와 같은 DB 를 쓴다(별도 파일을 만들지 않는다)."""
    return os.getenv("DB_PATH", "/app/data/logic_data.db")
