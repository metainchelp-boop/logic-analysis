"""DB 백업 회귀 — 「만들었다」가 아니라 「되돌릴 수 있다」를 지킨다.

⚠️ 이 시험이 생긴 경위 (2026-09-11 실측 사고)
   00:29 에 나간 배포가 컨테이너를 00:31:23 에 교체해, 00:30 백업의 gzip 이
   9.0%(243MB/2.7GB)에서 죽었다. 그런데 백업 로그는 「완료」만 찍었다 —
   **압축본이 끝까지 풀리는지 아무도 안 봤기 때문**이다.
   원본 .db 가 우연히 남아 있어 복구 수단이 살아 있었을 뿐이다.
   같은 날 보관 정리도 「파일 개수」로 세고 있어 **보관 2세대가 실질 1세대**였다.

표준 라이브러리만 쓴다 — 배포 게이트 환경에는 fastapi·apscheduler 가 없다.
"""

import gzip
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from db_backup import generation_of, plan_prune, verify_gzip, keep_raw_reason  # noqa: E402

P = "logic_analysis_backup_"


def _src(name):
    here = os.path.dirname(os.path.abspath(__file__))
    with io.open(os.path.join(here, "..", name), encoding="utf-8") as f:
        return f.read()


def test_generation_pairs_db_and_gz():
    """.db 와 .db.gz 는 **같은 세대**다 — 이걸 못 묶으면 보관 개수가 어긋난다."""
    assert generation_of(P + "20260911_003000.db") == "20260911_003000"
    assert generation_of(P + "20260911_003000.db.gz") == "20260911_003000"
    assert generation_of(P + "20260911_003000.db") == generation_of(P + "20260911_003000.db.gz")


def test_generation_ignores_other_files():
    """라이브 DB·잡파일을 백업으로 세면 안 된다 — 지우면 서비스가 죽는다."""
    for f in ("logic_data.db", "logic_data.db.bak", "rank_api_cache.json", "", "backups"):
        assert generation_of(f) is None, f"백업이 아닌데 세대로 잡혔다: {f}"


def test_prune_counts_generations_not_files():
    """⭐ 실제 사고 재현 — 압축이 끊겨 .db 가 남은 날.

    파일은 4개지만 세대는 3개다. keep=2 면 **가장 오래된 세대 하나만** 지워야 한다.
    종전(파일 개수) 방식은 파일 2개를 지워 9/10 세대까지 날렸다.
    """
    files = [P + "20260909_003000.db.gz",
             P + "20260910_003000.db.gz",
             P + "20260911_003000.db",       # 압축이 끊겨 남은 원본
             P + "20260911_003000.db.gz"]    # 깨진 압축본
    drop = plan_prune(files, keep=2)
    assert drop == [P + "20260909_003000.db.gz"], f"세대 기준이 아니다: {drop}"
    kept = [f for f in files if f not in drop]
    assert P + "20260910_003000.db.gz" in kept, "지난 세대가 밀려났다 — 종전 결함 재발"
    assert len({generation_of(f) for f in kept}) == 2, "보관 세대가 2개가 아니다"


def test_prune_keeps_whole_generation_together():
    """한 세대의 파일은 함께 남거나 함께 지워진다 — 반쪽만 남으면 복구 때 헷갈린다."""
    files = [P + "20260901_003000.db", P + "20260901_003000.db.gz",
             P + "20260911_003000.db.gz"]
    drop = plan_prune(files, keep=1)
    assert set(drop) == {P + "20260901_003000.db", P + "20260901_003000.db.gz"}, drop


def test_prune_keep_zero_and_negative_are_safe():
    files = [P + "20260911_003000.db.gz"]
    assert plan_prune(files, keep=0) == files
    assert plan_prune(files, keep=-1) == files
    assert plan_prune([], keep=2) == []


def test_verify_accepts_a_good_archive():
    payload = os.urandom(300_000)
    with tempfile.TemporaryDirectory() as d:
        gz = os.path.join(d, "ok.gz")
        with gzip.open(gz, "wb") as f:
            f.write(payload)
        ok, n, why = verify_gzip(gz, expect_bytes=len(payload))
        assert ok and n == len(payload) and why is None, (ok, n, why)


def test_verify_catches_the_real_failure_truncated_archive():
    """⭐ 실제 사고 재현 — 압축 중 프로세스가 죽어 파일이 잘린 경우.

    9/11 에는 9.0% 지점에서 끊겼다. 여기서도 앞부분만 남겨 같은 상황을 만든다.
    """
    payload = os.urandom(2_000_000)
    with tempfile.TemporaryDirectory() as d:
        gz = os.path.join(d, "cut.gz")
        with gzip.open(gz, "wb") as f:
            f.write(payload)
        full = os.path.getsize(gz)
        with io.open(gz, "r+b") as f:            # 9% 만 남기고 자른다
            f.truncate(max(32, int(full * 0.09)))
        ok, n, why = verify_gzip(gz, expect_bytes=len(payload))
        assert not ok, "잘린 압축본을 통과시켰다 — 9/11 사고가 그대로 재발한다"
        assert why, "왜 못 쓰는지 말하지 않는다"
        assert n < len(payload), (n, len(payload))


def test_verify_catches_size_mismatch_without_exception():
    """⚠️ 「예외가 안 났다」만으로 판정하면 안 된다 — 크기까지 봐야 한다."""
    payload = b"x" * 1000
    with tempfile.TemporaryDirectory() as d:
        gz = os.path.join(d, "short.gz")
        with gzip.open(gz, "wb") as f:
            f.write(payload)
        ok, n, why = verify_gzip(gz, expect_bytes=len(payload) + 1)
        assert not ok and "다르다" in (why or ""), (ok, n, why)


def test_verify_rejects_empty_archive_when_size_unknown():
    with tempfile.TemporaryDirectory() as d:
        gz = os.path.join(d, "empty.gz")
        with gzip.open(gz, "wb"):
            pass
        ok, n, why = verify_gzip(gz)
        assert not ok and n == 0, (ok, n, why)


def test_keep_raw_reason_speaks_only_on_failure():
    assert keep_raw_reason(True, None) is None
    msg = keep_raw_reason(False, "EOFError: ...")
    assert msg and "원본" in msg, msg


def test_scheduler_verifies_before_deleting_the_raw_copy():
    """배선 검사 — 검증을 통과하기 전에 원본을 지우면 안 된다.

    ⚠️ 모듈만 떼어 시험하면 「scheduler 가 그걸 부르는지」는 안 지켜진다.
       종전 결함이 바로 그 자리(호출부)에 있었으므로 소스로 확인한다.
    """
    s = _src("scheduler.py")
    assert "from db_backup import verify_gzip" in s, "압축 검증을 안 부른다"
    assert "from db_backup import plan_prune" in s, "세대 기준 보관 정리를 안 쓴다"
    # 압축 블록 안에서 os.remove(raw_path) 가 검증 통과(ok) 분기 뒤에 오는지.
    blk = s.split("# gzip 압축 →", 1)[1].split("\n    try:\n        logger.info", 1)[0]
    assert "verify_gzip" in blk, "압축 블록에 검증이 없다"
    i_ok = blk.find("if ok:")
    i_rm = blk.find("os.remove(raw_path)")
    assert 0 <= i_ok < i_rm, "검증 전에 원본을 지운다 — 깨진 압축본만 남는다(9/11 사고)"
    assert "os.remove(gz_path)" in blk, "깨진 압축본을 버리지 않는다"


def test_startup_backup_path_is_fixed_too():
    """⭐ 백업 경로는 **둘**이다 — 스케줄(00:30)과 앱 기동.

    2026-09-11 에 스케줄 경로만 고치고 기동 경로를 놓쳤다. 그날 배포 직후 기동 백업이
    돌면서 00:30 세대의 비압축본을 지웠는데, **그것이 그 시점 유일하게 복구 가능한
    백업**이었다(자기가 만든 것이 정상이라 무해했을 뿐이다).
    ⇒ 한쪽만 고치면 다른 쪽이 같은 사고를 낸다. 두 경로를 함께 지킨다.
    """
    m = _src("main.py")
    i = m.find("def _backup_db_on_startup(")
    assert i >= 0, "기동 백업 함수가 없다 — 이름이 바뀌었으면 이 시험을 함께 고칠 것"
    body = m[i:i + 9000]
    assert "from db_backup import verify_gzip" in body, \
        "기동 백업이 압축 검증을 안 부른다 — 깨진 압축본이 그대로 백업이 된다"
    assert "from db_backup import plan_prune" in body, \
        "기동 백업이 세대 기준 정리를 안 쓴다 — 파일 개수로 세면 지난 세대가 밀려난다"
    i_ok = body.find("if not _ok:")
    i_rm = body.find("os.remove(raw_path)")
    assert 0 <= i_ok < i_rm, "검증 전에 원본을 지운다 — 9/11 사고가 이 경로에서 재발한다"


def test_both_backup_paths_share_one_rule():
    """두 경로가 같은 판단 규칙(db_backup)을 쓰는지 — 복사본이 갈라지면 또 어긋난다."""
    for f in ("main.py", "scheduler.py"):
        src = _src(f)
        assert "from db_backup import" in src, f"{f} 가 공용 백업 규칙을 안 쓴다"
    # 옛 방식(파일 개수를 세는 while 루프)이 남아 있지 않은지
    m = _src("main.py")
    i = m.find("def _backup_db_on_startup(")
    body = m[i:i + 9000]
    assert "while len(bks) > keep" not in body, "파일 개수로 세는 옛 정리 루프가 남아 있다"


def test_backup_keep_is_at_least_two_generations():
    s = _src("scheduler.py")
    assert "BACKUP_KEEP = 2" in s or "BACKUP_KEEP = 3" in s, \
        "보관 세대가 1개면 그날 백업이 깨지면 되돌릴 것이 없다"


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
