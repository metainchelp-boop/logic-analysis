"""짧은 쓰기(📡 heartbeat · 🧱 막힘 보고)가 배치의 긴 쓰기 잠금에 밀려 500 으로 죽지 않게 한다 (2026-09-23).

⚠️ 왜 — 9/23 01:0x(00:30 백업·01:00 보관정책)와 08:00~08:35(순위 추적 배치)에 heartbeat·blocked 가
   `sqlite3.OperationalError: database is locked` 로 **500** 을 돌려줬다(기계 2대 × 각 2건씩).
   종전 연결은 `timeout=10` 이라 배치가 10초 넘게 쓰기 잠금을 쥐면 그대로 죽었다.
   수집 업로드(/serp)는 살아 있었으니 데이터 손실은 없지만, 「살아있음」 신호가 빠지면
   서버 화면이 그 기계를 「신호 끊김」 직전으로 오해할 수 있다.

하는 것 = **기다리고(30초) · 다시 시도하고(3번) · 그래도 안 되면 503(db-busy)** — 500 traceback 대신
정직한 「지금 바쁨」. 확장은 heartbeat 응답을 판정에 쓰지 않으므로 어느 쪽이든 수집은 멈추지 않는다.
⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없어 이 조각을 따로 뺐다(split_rule 선례).
"""
import sqlite3
import time
from typing import Callable, Any

LOCKED_MARKERS = ("database is locked", "database table is locked")
DEFAULT_TIMEOUT = 30.0
DEFAULT_TRIES = 3
DEFAULT_BACKOFF = 0.5


class DbBusy(Exception):
    """재시도를 다 써도 잠금이 안 풀렸다 — 호출자는 503 으로 바꾼다(500 아님)."""


def is_locked_error(e: BaseException) -> bool:
    return isinstance(e, sqlite3.OperationalError) and any(m in str(e) for m in LOCKED_MARKERS)


def connect_rw(path: str, timeout: float = DEFAULT_TIMEOUT) -> sqlite3.Connection:
    """쓰기용 연결 — busy 대기를 연결 timeout 과 PRAGMA 양쪽에 건다."""
    conn = sqlite3.connect(path, timeout=timeout)
    try:
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    except Exception:
        pass
    return conn


def write_with_retry(path: str, fn: Callable[[sqlite3.Connection], Any], *,
                     tries: int = DEFAULT_TRIES, backoff: float = DEFAULT_BACKOFF,
                     timeout: float = DEFAULT_TIMEOUT, sleep: Callable[[float], None] = time.sleep) -> Any:
    """fn(conn) 을 실행한다. 잠금 오류면 backoff 만큼 쉬고 다시(최대 tries). 다른 오류는 그대로 올린다.

    ⚠️ 잠금 외 오류를 삼키지 않는다 — 스키마 오류·자료 오류를 「바쁨」으로 가리면 더 나쁜 고장이 된다.
    """
    last: Exception = None
    for i in range(max(1, int(tries))):
        conn = connect_rw(path, timeout)
        try:
            return fn(conn)
        except sqlite3.OperationalError as e:
            if not is_locked_error(e):
                raise
            last = e
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()
        if i < tries - 1:
            sleep(backoff * (i + 1))
    raise DbBusy(str(last) if last else "database is locked")
