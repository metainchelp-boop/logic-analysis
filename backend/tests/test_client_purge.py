"""업체 삭제 회귀 — 자식을 남기지 않는다. 삭제 경로가 몇 개든 같은 목록을 쓴다.

⚠️ 이 시험이 생긴 경위 (2026-09-11 실측)
   업체 하드삭제 경로가 **5개**였고 지우는 자식이 제각각이었다. 특히
   `clients.py:delete_client` 는 `clients` 행만 지웠는데, 그 파일의 연결만
   **`PRAGMA foreign_keys=ON` 을 안 켠다** — 그래서 ON DELETE CASCADE 가 안 돌아
   분석·순위이력이 통째로 고아가 됐다(진단이 세던 「고아 순위행」의 출처).

   ⭐ 교훈 — 같은 일을 하는 코드가 몇 개인지 먼저 센다.
      오늘만 세 번째다: 백업 경로 2개 · 큐 되먹임 2자리 · 삭제 경로 5개.

표준 라이브러리만 쓴다 — 배포 게이트 환경에 fastapi 가 없다.
"""

import io
import os
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from client_purge import CHILD_TABLES, purge_client_children, prune_orphans, orphan_counts  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))


def _src(name):
    with io.open(os.path.join(_HERE, "..", name), encoding="utf-8") as f:
        return f.read()


def _fixture():
    """업체 2곳 + 자식 몇 줄. foreign_keys 는 **끈 채**로 만든다 — 사고 당시와 같은 조건."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "t.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT)")
    for t, col in CHILD_TABLES:
        c.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, {col} INTEGER)")
    c.execute("INSERT INTO clients (id, name) VALUES (1,'가'),(2,'나')")
    for t, col in CHILD_TABLES:
        c.executemany(f"INSERT INTO {t} ({col}) VALUES (?)", [(1,), (1,), (2,)])
    c.commit()
    return c


def test_purge_removes_every_child_of_that_client_only():
    c = _fixture()
    removed = purge_client_children(c, 1)
    c.commit()
    assert set(removed) == {t for t, _ in CHILD_TABLES}, f"안 지운 표가 있다: {removed}"
    for t, col in CHILD_TABLES:
        mine = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=1").fetchone()[0]
        other = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=2").fetchone()[0]
        assert mine == 0, f"{t} 에 자기 자식이 남았다"
        assert other == 1, f"{t} 에서 **남의 업체 자식**을 지웠다 — 치명적"


def test_purge_does_not_touch_the_client_row():
    """부모는 호출부가 지운다 — 여기서 지우면 트랜잭션 순서가 꼬인다."""
    c = _fixture()
    purge_client_children(c, 1)
    assert c.execute("SELECT COUNT(*) FROM clients WHERE id=1").fetchone()[0] == 1


def test_prune_cleans_what_old_paths_left_behind():
    """⭐ 실제 사고 재현 — 부모만 지워 자식이 고아가 된 상태."""
    c = _fixture()
    c.execute("DELETE FROM clients WHERE id=1")      # 종전 clients.py 가 하던 그대로
    c.commit()
    left = orphan_counts(c)
    assert left, "고아가 안 생겼다 — 고정물이 사고를 재현하지 못한다"
    removed = prune_orphans(c)
    c.commit()
    assert set(removed) == {t for t, _ in CHILD_TABLES}, removed
    assert orphan_counts(c) == {}, "고아가 남았다"
    for t, col in CHILD_TABLES:
        assert c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=2").fetchone()[0] == 1, \
            f"{t} — 살아 있는 업체의 자식까지 지웠다"


def test_missing_table_is_not_fatal():
    """표가 아직 없는 DB(구버전·신설 직후)에서도 나머지는 지워야 한다."""
    c = _fixture()
    c.execute(f"DROP TABLE {CHILD_TABLES[0][0]}")
    c.commit()
    removed = purge_client_children(c, 1)
    assert CHILD_TABLES[1][0] in removed, "한 표가 없다고 나머지를 포기했다"


def test_every_hard_delete_path_purges_children():
    """⭐ 핵심 — `DELETE FROM clients` 를 하는 **모든 자리**가 자식을 먼저 치운다.

    한 자리만 빠져도 그 경로가 고아를 만든다(2026-09-11 에 실제로 그랬다).
    새 경로가 생기면 이 시험이 먼저 깨진다.
    """
    bad = []
    for f in ("clients.py", "client_dashboard.py"):
        src = _src(f)
        lines = src.splitlines()
        for i, l in enumerate(lines):
            if re.search(r"DELETE FROM clients\b", l):
                back = "\n".join(lines[max(0, i - 14):i])
                if "purge_client_children" not in back:
                    bad.append(f"{f}:{i+1}  {l.strip()[:60]}")
    assert not bad, ("업체를 지우면서 자식을 안 치우는 자리가 있다:\n  "
                     + "\n  ".join(bad))


def test_child_list_covers_the_tables_that_caused_the_incident():
    names = {t for t, _ in CHILD_TABLES}
    for must in ("client_analyses", "client_rank_history", "reports"):
        assert must in names, f"{must} 가 자식 목록에서 빠졌다"


def test_logs_are_kept_on_purpose():
    """기록(로그)·인수인계는 업체가 없어져도 남긴다 — 목록에 들어가면 안 된다."""
    names = {t for t, _ in CHILD_TABLES}
    for keep in ("api_usage_logs", "handover_transfer_request", "report_owner_sync_log"):
        assert keep not in names, f"{keep} 은 업체 삭제로 지울 성격이 아니다"


def test_bridge_job_commits_and_closes():
    """고아 정리가 커밋·닫기를 하는지 — 안 하면 아무것도 안 지워지고 연결이 샌다."""
    s = _src("rank_link.py")
    i = s.find("from client_purge import prune_orphans")
    assert i >= 0, "01:20 잡이 자식 고아 정리를 안 부른다"
    blk = s[i:i + 700]
    assert ".commit()" in blk, "커밋이 없다 — DELETE 가 사라진다"
    assert ".close()" in blk, "닫기가 없다 — 연결이 샌다"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
