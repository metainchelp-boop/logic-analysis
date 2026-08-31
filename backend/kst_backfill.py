"""서버 표의 시각 기본값이 UTC 인 것을 한 번만 바로잡는다 (2026-08-31).

## 무엇이 잘못됐나

`reports` 표의 서버 정의는 `created_at TEXT DEFAULT CURRENT_TIMESTAMP` 다.
SQLite 에서 `CURRENT_TIMESTAMP` 는 **UTC** 라, 월요일 09:40 KST 에 만든 주간 보고서가
`00:40` 으로 적힌다(9시간 이르게). ①(메타 전산)이 2026-08-24 에 이 어긋남을 통지했고,
2026-08-31 서버 실측으로 사실임을 확인했다.

⚠️ **코드에는 `datetime('now','localtime')` 로 적혀 있다.** 그런데도 서버가 UTC 인 이유는
   `CREATE TABLE IF NOT EXISTS` 가 **이미 있는 표를 절대 고치지 않기** 때문이다 —
   그 표는 코드가 바뀌기 전에 만들어졌고, 옛 정의가 그대로 남았다.
   ⇒ 표 정의만 보고 「코드가 그러니 서버도 그렇겠지」라고 읽으면 안 된다.

## 왜 표를 다시 만들지 않나

SQLite 는 칸의 기본값을 바꾸는 ALTER 를 지원하지 않는다. 바꾸려면 표를 새로 만들어
복사하고 갈아끼워야 하는데, `reports`·`clients` 는 서비스의 중심 표라 그 위험이
얻는 것보다 크다. 대신 **넣을 때 KST 를 명시**한다(호출부 수정) — 기본값을 아예 안 쓴다.

## 이 파일이 하는 일

이미 UTC 로 적힌 기존 행을 **한 번만** +9시간 보정한다. 표준 라이브러리만 쓴다
(배포 게이트 환경에 fastapi·apscheduler 가 없어, 그것을 임포트하는 모듈에 두면 검사할 수 없다).

## 안전 근거 (2026-08-31 서버 실측)

- 자동 보고서 977건이 **전부 `00:40`** 한 무리 — 자동 생성은 항상 월 09:40 KST 실행이므로
  `00:40` 은 UTC 로 적혔다는 뜻이다. 섞인 무리가 없다.
- id 순으로 시각이 **역행하는 곳 0** — 처음부터 끝까지 한 시계만 썼다.
- 15시 이후에 적힌 행 **0건** — +9시간 해도 **날짜가 바뀌는 행이 없다**.
  ①은 날짜 축으로 읽으므로 그쪽 계산은 흔들리지 않는다.
- ① 은 `saveNew`(새 행만 INSERT)로 가져가 이미 자기 DB 에 복사해 뒀다 —
  우리가 고쳐도 ①의 기존 값은 안 바뀐다(그쪽 보관 판정은 84일이라 9시간은 무의미).

## ⚠️ clients 는 보정하지 않는다

`clients.created_at` 도 서버 기본값이 UTC 지만, **보정할 것이 없다.**

실측(2026-08-31) 시각대 분포가 10~23시에 몰려 있고 00~09시는 다 합쳐 5곳뿐이다.
전부 UTC 라면 실제 등록이 19시~새벽 3시에 몰렸다는 뜻이 되는데, 그런 회사는 없다 —
즉 지금 값은 **사실상 전부 KST** 이고 `clients.py` 의 기본값 경로로 들어온 행이 거의 없다.
남은 5곳도 「UTC 로 적힌 것」인지 「밤늦게 등록한 것」인지 가릴 방법이 없다.
⇒ 앞으로 들어올 행만 바로잡고(호출부에 KST 명시) 기존 행은 손대지 않는다.

⚠️ 처음엔 「두 경로가 섞여 보정이 불가능하다」고 적었는데, 그건 코드만 보고 세운 가설이었다.
   실제 데이터는 「섞인 게 아니라 한쪽이 거의 안 쓰였다」였다 — 재 보기 전엔 단정하지 말 것.
"""
import logging
import os

logger = logging.getLogger(__name__)

# 마커 이름에 날짜를 박아 둔다 — 다음에 또 이런 일이 생겨도 어느 보정인지 구분된다.
MARKER_NAME = ".reports_kst_backfill_2026_08_31"


def marker_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), MARKER_NAME)


def pending_count(conn) -> int:
    """아직 UTC 로 남아 있는 행 수 — 보정 전후 비교용(읽기 전용)."""
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM reports WHERE created_at IS NOT NULL AND created_at <> ''"
        ).fetchone()[0]
    except Exception:
        return 0


def backfill(conn, max_id=None) -> int:
    """UTC 로 적힌 기존 행을 +9시간 보정한다. 옮긴 행 수를 돌려준다.

    `max_id` 를 주면 그 id 이하만 손댄다 — 부르는 쪽이 「보정 시점에 이미 있던 행」으로
    범위를 못박기 위한 것이다. 주지 않으면 그 자리에서 MAX(id) 를 읽어 같은 일을 한다.

    ⚠️ **경계를 두 겹으로 잠근다.** 호출부 수정이 배포된 뒤 새로 들어오는 행은 KST 로
       적히므로, 경계 없이 전부 더하면 **이미 맞는 행을 9시간 밀어 버린다.**

       ① `id <= max_id` — 부르는 쪽이 못박은 시점까지만.
       ② `created_at < 지금-1시간` — ①만으로는 구멍이 남는다. 이 보정은 부팅 1분 뒤에
          도는데, 그 1분 사이에 새 코드가 쓴 행이 들어오면 그 행도 max_id 안에 든다.
          그런데 새 코드가 쓴 행은 시각이 **지금과 거의 같고**, UTC 로 적힌 옛 행은
          아무리 최근이어도 **최소 9시간 뒤처져 보인다** — 이 한 줄이 둘을 완전히 가른다.

    ⚠️ 형식이 시각이 아닌 행(빈 값·짧은 값)은 건드리지 않는다 — `datetime()` 이 NULL 을
       돌려주면 값이 통째로 사라진다. 그것이 이 함수에서 가장 위험한 실수다.
    """
    if max_id is None:
        row = conn.execute("SELECT MAX(id) FROM reports").fetchone()
        max_id = (row[0] if row else None) or 0
    cur = conn.execute(
        "UPDATE reports"
        "   SET created_at = datetime(created_at, '+9 hours')"
        " WHERE id <= ?"
        "   AND created_at IS NOT NULL"
        "   AND length(created_at) >= 16"
        "   AND datetime(created_at) IS NOT NULL"
        "   AND created_at < datetime('now','localtime','-1 hour')",
        (max_id,))
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def run_once(db_path: str) -> int:
    """마커가 없을 때만 1회 실행. 옮긴 행 수를 돌려준다(이미 했으면 -1).

    실패하면 마커를 만들지 않는다 — 다음 배포에서 다시 시도한다.
    (VACUUM 1회 잡과 같은 규칙이다. 규칙을 새로 만들지 않는다.)
    """
    import sqlite3
    mk = marker_path(db_path)
    if not os.path.exists(db_path) or os.path.exists(mk):
        return -1
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        row = conn.execute("SELECT MAX(id) FROM reports").fetchone()
        max_id = (row[0] if row else None) or 0
        n = backfill(conn, max_id)
        conn.commit()
        with open(mk, "w") as f:
            f.write("done")
        logger.info(f"🕘 [시각 보정] 보고서 {n}건을 KST 로 옮겼다 (id {max_id} 까지 · 1회)")
        return n
    except Exception as e:
        logger.error(f"[시각 보정] 실패(무시·다음 배포 재시도): {e}")
        return -1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
