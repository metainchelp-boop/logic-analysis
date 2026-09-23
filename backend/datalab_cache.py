"""데이터랩 결과 재사용 보관함 — 일꾼 5개가 **같은 보관함**을 쓴다 (대표 확정 2026-09-23 · 결정 C).

⚠️ **왜 만드나 — 캐시가 있는데도 하루 한도가 바닥났다.**
   종전 캐시는 `datalab.py` 의 **파이썬 메모리(1시간)** 였다. 그런데 로직분석 서버는
   uvicorn 일꾼이 **5개**(`backend/Dockerfile` `--workers 5`)이고 메모리는 일꾼마다 따로다.
   같은 키워드를 1시간 안에 다시 물어도 **다른 일꾼이 받으면 네이버에 또 묻는다**.
   배포·재시작 때마다 메모리도 통째로 비워진다.
   9/23 전수조사에서 데이터랩 하루 한도가 오후에 바닥나 **자정까지 성별·연령·추이 칸이 빈 채** 나갔다.

   그래서 두 가지를 바꾼다.
     ① 보관 자리를 **DB 한 곳**으로 — 일꾼 5개·재시작 뒤에도 같은 결과를 다시 쓴다.
     ② 재사용 기간을 **1시간 → 24시간** 으로 — 같은 키워드는 하루 한 번만 네이버에 묻는다.

⚠️ **정확도를 잃지 않는 이유** — 데이터랩이 주는 값은 「최근 1개월 성별·연령 비율」 ·
   「24개월 월별 추이」 · 「요일 패턴」이다. 하루 사이에 바뀌는 폭이 작고, 월 단위 추이는
   달이 바뀌어야 움직인다. 하루 지난 값은 **어제까지의 같은 창**이다(지어낸 값이 아니다).

⚠️ **성공한 값만 보관한다**(호출자 `datalab._cached` 규칙 그대로). 실패·빈값은 보관하지 않아
   다음 호출이 다시 묻는다 — 빈 결과를 24시간 동안 굳히면 한도 소진이 풀려도 빈 칸이 이어진다.

⚠️ **한도 소진 표시도 함께 나눈다.** 한 일꾼이 「오늘 한도 끝」을 받으면 나머지 4개도
   자정까지 호출을 멈춘다(종전엔 일꾼마다 한 번씩 더 두드렸다).

⚠️ **어떤 실패도 밖으로 내보내지 않는다.** 보관함이 고장 나면 종전처럼 메모리·실호출로
   돌아간다 — 분석이 멈추는 것보다 한도를 조금 더 쓰는 쪽이 낫다.
⚠️ 표준 라이브러리만 — 배포 회귀 게이트가 fastapi·requests 없이 import 한다(split_rule 선례).
"""

import json
import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

TTL_SECONDS = 24 * 3600          # 재사용 기간 — 하루 (종전 메모리 캐시 1시간)
KEEP_SECONDS = 7 * 24 * 3600     # 이보다 오래된 줄은 지운다(표가 한없이 커지지 않게)
PRUNE_EVERY = 3600               # 지우기는 한 일꾼당 한 시간에 한 번만
QUOTA_KEY = "__quota_block_until__"
QUOTA_READ_EVERY = 30            # 한도 표시는 30초에 한 번만 DB 에서 다시 읽는다
READ_TIMEOUT = 5.0
WRITE_TIMEOUT = 5.0

_last_prune = [0.0]
_quota_seen = {"at": 0.0, "until": 0.0}


def _path():
    return os.getenv("DB_PATH", DB_PATH)


def _connect(timeout):
    conn = sqlite3.connect(_path(), timeout=timeout)
    try:
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    except Exception:
        pass
    return conn


def ensure_table(conn) -> None:
    """멱등. ⚠️ 호출자 트랜잭션 안이면 commit 하지 않는다(keyword_mute 에서 정리한 규칙)."""
    was_in_txn = bool(getattr(conn, "in_transaction", False))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS datalab_cache (
            k        TEXT PRIMARY KEY,
            v        TEXT NOT NULL,
            saved_at REAL NOT NULL
        )""")
    if not was_in_txn:
        conn.commit()


def lookup(key: str, ttl: float = TTL_SECONDS, now: float = None):
    """(보관된 값, 보관 시각) — 없거나 기간이 지났거나 읽기 실패면 (None, None)."""
    if not key:
        return None, None
    now = time.time() if now is None else now
    conn = None
    try:
        conn = _connect(READ_TIMEOUT)
        ensure_table(conn)
        r = conn.execute("SELECT v, saved_at FROM datalab_cache WHERE k=?", (key,)).fetchone()
        if not r:
            return None, None
        saved_at = float(r[1])
        if (now - saved_at) >= ttl:
            return None, None
        return json.loads(r[0]), saved_at
    except Exception as e:
        logger.debug(f"[데이터랩보관] 읽기 실패(무시 · 실호출로 진행): {e}")
        return None, None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get(key: str, ttl: float = TTL_SECONDS, now: float = None):
    """보관된 값(dict·list 등). 없거나 기간이 지났거나 읽기 실패면 None."""
    return lookup(key, ttl, now)[0]


def put(key: str, value, now: float = None) -> bool:
    """보관한다. 빈값(None·{}·[])은 보관하지 않는다. 실패해도 False 만 돌려준다."""
    if not key or not value:
        return False
    now = time.time() if now is None else now
    conn = None
    try:
        payload = json.dumps(value, ensure_ascii=False)
        conn = _connect(WRITE_TIMEOUT)
        ensure_table(conn)
        conn.execute("INSERT OR REPLACE INTO datalab_cache(k, v, saved_at) VALUES (?,?,?)",
                     (key, payload, float(now)))
        if now - _last_prune[0] >= PRUNE_EVERY:
            _last_prune[0] = now
            conn.execute("DELETE FROM datalab_cache WHERE saved_at < ? AND k != ?",
                         (float(now) - KEEP_SECONDS, QUOTA_KEY))
        conn.commit()
        return True
    except Exception as e:
        logger.debug(f"[데이터랩보관] 쓰기 실패(무시): {e}")
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def mark_quota_until(until_epoch: float) -> None:
    """한도 소진 — 이 시각까지 모든 일꾼이 호출을 멈춘다."""
    _quota_seen["until"] = max(_quota_seen["until"], float(until_epoch))
    _quota_seen["at"] = time.time()
    put(QUOTA_KEY, {"until": float(until_epoch)})


def quota_blocked_until(now: float = None) -> float:
    """다른 일꾼이 남긴 한도 소진 표시까지 포함한 차단 시각(epoch). 읽기 실패면 알고 있던 값."""
    now = time.time() if now is None else now
    if now - _quota_seen["at"] < QUOTA_READ_EVERY:
        return _quota_seen["until"]
    _quota_seen["at"] = now
    v = get(QUOTA_KEY, ttl=KEEP_SECONDS, now=now)
    try:
        if isinstance(v, dict) and v.get("until"):
            _quota_seen["until"] = max(_quota_seen["until"], float(v["until"]))
    except Exception:
        pass
    return _quota_seen["until"]
