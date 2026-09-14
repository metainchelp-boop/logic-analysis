"""시작 시 백업 — 워커 간 잠금 회귀 시험 (2026-09-14)

무엇을 막는가 — **워커가 같은 백업 파일을 동시에 쓰는 것.**

이 앱은 `gunicorn -w 3` 으로 뜨고, FastAPI lifespan 은 **워커마다** 돈다.
백업 파일 이름이 `초` 단위 시각이라 세 워커가 **같은 이름**을 잡고 동시에 쓴다.
2026-09-14 배포 #437 기동 로그가 그 장면이다(UTC):

    06:34:59  ✅ DB 백업 완료: …_20260914_153431.db
    06:37:46  ✅ DB 백업 완료: …_20260914_153431.db     ← 같은 파일에 두 번
    06:38:57  ❌ 압축본이 복구에 쓸 수 없다 — Error -3 … invalid stored block lengths
    06:40:14  ❌ 압축본이 복구에 쓸 수 없다 — FileNotFoundError: …db.gz

둘이 같은 `.gz` 에 겹쳐 써서 깨졌고, 한쪽이 깨진 것을 지우자 다른 쪽은 못 찾았다.
⇒ 압축이 실패해 **비압축 2.7GB** 가 남는다(디스크 68%까지 찼다).

⚠️ 시험 방법 — **말로만 확인하지 않는다.** 실제로 자식 프로세스를 여럿 띄워
   같은 잠금을 동시에 잡게 하고, **정확히 하나만** 들어가는지 센다.
   `fcntl.flock` 은 프로세스가 죽으면 커널이 푸는 것까지 함께 확인한다
   (잠금 파일을 만들었다 지우는 방식이었다면 죽은 뒤 영영 안 도는 더 나쁜 고장이 된다).

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi 가 없어 main.py 를 import 할 수 없다).
"""
import ast
import multiprocessing as mp
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)

_pass = _fail = 0


def ok(name, cond, note=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}" + (f"  — {note}" if note else ""))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _func_src(src, name):
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    return ""


# ==================================================================
# ① 코드에 잠금이 실제로 걸려 있는가
# ==================================================================
def test_lock_is_wired():
    src = read(os.path.join(BACKEND, "main.py"))
    wrapper = _func_src(src, "_backup_db_on_startup")
    inner = _func_src(src, "_backup_db_on_startup_locked")

    ok("잠금 래퍼 _backup_db_on_startup 이 있다", bool(wrapper))
    ok("실제 작업은 _backup_db_on_startup_locked 로 분리됐다", bool(inner))
    ok("래퍼가 flock 을 쓴다", "fcntl.flock" in wrapper and "LOCK_EX" in wrapper,
       "잠금이 없으면 워커마다 같은 파일을 동시에 쓴다")
    ok("잠금은 **비차단**이다(LOCK_NB)", "LOCK_NB" in wrapper,
       "차단으로 걸면 워커 3개가 줄 서서 백업을 3번 한다 — 건너뛰어야 한다")
    ok("잠금을 못 잡으면 건너뛴다", "건너뜁니다" in wrapper or "return" in wrapper.split("BlockingIOError")[-1][:200])
    ok("끝나면 반드시 푼다(finally)", "finally:" in wrapper and "LOCK_UN" in wrapper)
    ok("fcntl 을 못 쓰면 종전대로 진행한다(백업이 사라지지 않는다)",
       "except Exception:" in wrapper.split("import fcntl")[-1][:160],
       "잠금 때문에 백업이 아예 안 돌면 더 나쁜 고장이다")

    # 실제 백업 본문은 래퍼를 통해서만 불린다
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_backup_db_on_startup_locked"]
    ok("본문 호출은 래퍼 안 2곳뿐이다", len(calls) == 2, f"{len(calls)}곳에서 부른다")

    ok("lifespan 은 래퍼를 부른다(본문을 직접 부르지 않는다)",
       "_backup_db_on_startup()" in src and "    _backup_db_on_startup_locked()\n" not in src)


# ==================================================================
# ② 잠금이 **실제로** 워커를 한 명만 들여보내는가 (프로세스 여럿으로 재현)
# ==================================================================
def _worker(lock_path, hold_sec, counter, barrier):
    """래퍼와 같은 방식으로 잠금을 잡아 본다. 성공하면 counter 를 올린다."""
    import fcntl
    barrier.wait()                       # 셋이 정확히 동시에 달려든다
    fd = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError, BlockingIOError):
        if fd is not None:
            os.close(fd)
        return                            # 다른 워커가 하는 중 — 건너뜀
    with counter.get_lock():
        counter.value += 1
    time.sleep(hold_sec)                  # 백업하는 동안 붙들고 있는다
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _suicide_worker(lock_path, ready):
    """잠금을 잡은 채로 **죽는다** — 커널이 자동으로 푸는지 보기 위해."""
    import fcntl
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ready.set()
    time.sleep(30)                        # 부모가 죽인다


def test_lock_actually_serialises():
    try:
        import fcntl  # noqa: F401
    except Exception:
        ok("이 환경에 fcntl 이 있다", False, "잠금 동작을 재현할 수 없다")
        return

    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, ".startup_backup.lock")

        # 워커 3개가 동시에 — 정확히 1개만 들어가야 한다
        counter = mp.Value("i", 0)
        barrier = mp.Barrier(3)
        ps = [mp.Process(target=_worker, args=(lock, 1.2, counter, barrier)) for _ in range(3)]
        for p in ps:
            p.start()
        for p in ps:
            p.join(timeout=20)
        ok("워커 3개가 동시에 달려들어도 **1개만** 백업한다", counter.value == 1,
           f"{counter.value}개가 들어갔다 — 같은 파일을 겹쳐 쓴다")

        # 잠금이 풀린 뒤에는 다시 들어갈 수 있어야 한다(영영 막히면 안 된다)
        counter2 = mp.Value("i", 0)
        barrier2 = mp.Barrier(1)
        p = mp.Process(target=_worker, args=(lock, 0.1, counter2, barrier2))
        p.start()
        p.join(timeout=20)
        ok("앞 백업이 끝나면 다음 기동은 다시 들어간다", counter2.value == 1,
           "한 번 잠기면 영영 안 도는 고장이 된다")


def test_lock_survives_a_dead_worker():
    """잠금을 쥔 프로세스가 죽어도 다음 사람이 들어갈 수 있어야 한다.

    ⚠️ 이것이 `flock` 을 고른 이유다 — 잠금 '파일'을 만들었다 지우는 방식이면
       프로세스가 죽는 순간 파일이 남아 **다음 기동부터 영영 백업이 안 돈다.**
    """
    try:
        import fcntl  # noqa: F401
    except Exception:
        return
    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, ".startup_backup.lock")
        ready = mp.Event()
        victim = mp.Process(target=_suicide_worker, args=(lock, ready))
        victim.start()
        got = ready.wait(timeout=20)
        ok("먼저 온 워커가 잠금을 잡았다", got)
        victim.kill()                     # 배포가 컨테이너를 갈아 치우는 상황
        victim.join(timeout=20)

        counter = mp.Value("i", 0)
        barrier = mp.Barrier(1)
        p = mp.Process(target=_worker, args=(lock, 0.1, counter, barrier))
        p.start()
        p.join(timeout=20)
        ok("잠금을 쥔 워커가 죽어도 다음 워커가 들어간다(커널이 푼다)", counter.value == 1,
           "잠금이 남아 영영 백업이 안 도는 고장 — 원래 사고보다 나쁘다")


# ==================================================================
# ③ 이 시험이 배포 게이트에 등록돼 있는가
# ==================================================================
def test_self_registered_in_gate():
    me = os.path.basename(__file__)
    dy = read(os.path.join(ROOT, ".github", "workflows", "deploy.yml"))
    ok(f"deploy.yml 이 {me} 를 부른다", me in dy, "만들어 놓고 안 도는 시험이 된다")


if __name__ == "__main__":
    print("=== 시작 시 백업 워커 잠금 회귀 시험 ===")
    test_lock_is_wired()
    test_lock_actually_serialises()
    test_lock_survives_a_dead_worker()
    test_self_registered_in_gate()
    print(f"\n통과 {_pass} · 실패 {_fail}")
    sys.exit(1 if _fail else 0)
