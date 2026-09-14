"""배포가 **어느 파일을 집어 가는가** 회귀 시험 (2026-09-14)

무엇을 막는가 — **엉뚱한 파일을 읽고 서버 동작을 단정하는 것.**

이 저장소에는 같은 일을 하는 파일이 **둘씩** 있다:

    저장소 루트  Dockerfile          CMD gunicorn -w 3      ← 배포에 안 쓰인다
    backend/     Dockerfile          CMD uvicorn --workers 5 ← 실제로 쓰이는 것
    저장소 루트  docker-compose.yml  build: .                ← 배포에 안 쓰인다
    deploy.yml 이 서버에 써 넣는 compose  build: ./backend   ← 실제로 쓰이는 것

2026-09-14 실사고 — 백업이 깨진 원인을 파다가 **루트 Dockerfile 을 읽고**
「gunicorn 워커 3개」라고 단정해 PR·커밋·보고서에 적었다. 서버는 **uvicorn 워커 5개**였다.
원인 진단(여럿이 돈다)은 맞았지만 수와 실행기를 틀리게 적었다.

⭐ 교훈 — 「설정 파일에 뭐라고 적혀 있나」가 아니라 **「배포가 어느 파일을 집어 가나」**를 따라갈 것.

이 시험이 지키는 것 셋:
  ① 배포가 쓰는 compose 는 여전히 `build: ./backend` 인가 (바뀌면 아래 ②③의 전제가 무너진다)
  ② 죽은 두 파일에 **「배포에 안 쓰인다」 경고**가 남아 있는가 (지워지면 다음 사람이 또 속는다)
  ③ 실제로 쓰이는 `backend/Dockerfile` 에 CMD 가 있고, 그 워커 수가 경고문과 **일치**하는가

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi·pyyaml 이 없다).
"""
import os
import re
import sys

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


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ==================================================================
# ① 배포가 실제로 집어 가는 것 — deploy.yml 이 서버에 써 넣는 compose
# ==================================================================
def test_deploy_builds_from_backend():
    dy = read(".github", "workflows", "deploy.yml")

    m = re.search(r"cat > docker-compose\.yml << 'COMPEOF'(.*?)COMPEOF", dy, re.S)
    ok("deploy.yml 이 서버에 compose 를 직접 써 넣는다", m is not None,
       "이 구조가 바뀌면 이 시험의 전제가 통째로 달라진다 — 주석부터 다시 쓸 것")
    if not m:
        return
    gen = m.group(1)

    ok("그 compose 는 build: ./backend 다", "build: ./backend" in gen,
       "여기가 바뀌면 루트 Dockerfile 이 살아난다 — 죽은 파일 경고문을 지워야 한다")
    ok("그 compose 는 루트를 빌드하지 않는다",
       not re.search(r"^\s*build:\s*\.\s*$", gen, re.M),
       "루트와 backend 를 둘 다 빌드하면 어느 쪽이 도는지 또 헷갈린다")
    ok("컨테이너 이름은 그대로다", "container_name: logic-analysis" in gen)


# ==================================================================
# ② 죽은 두 파일에 경고가 남아 있는가
# ==================================================================
def test_dead_files_warn():
    for path, hint in [("Dockerfile", "backend/Dockerfile"),
                       ("docker-compose.yml", "deploy.yml")]:
        src = read(path)
        head = src[:1600]
        ok(f"{path} 맨 위에 「배포에 쓰이지 않습니다」 경고가 있다",
           "배포에 쓰이지 않습니다" in head,
           "경고가 없으면 다음 사람이 이 파일을 읽고 서버 동작을 단정한다")
        ok(f"{path} 경고가 **어디를 봐야 하는지** 알려 준다", hint in head,
           "「안 쓰인다」만 적으면 그럼 어디를 보라는 건지 모른다")


# ==================================================================
# ③ 실제로 쓰이는 파일 — CMD 가 있고 경고문과 수가 맞는가
# ==================================================================
def _backend_workers():
    src = read("backend", "Dockerfile")
    m = re.search(r'CMD\s*\[(.*?)\]', src, re.S)
    if not m:
        return None, ""
    cmd = m.group(1)
    w = re.search(r'"--workers"\s*,\s*"(\d+)"', cmd)
    return (int(w.group(1)) if w else None), cmd


def test_backend_dockerfile_is_the_real_one():
    workers, cmd = _backend_workers()
    ok("backend/Dockerfile 에 CMD 가 있다", bool(cmd))
    ok("그 CMD 는 uvicorn 이다", "uvicorn" in cmd,
       "실행기가 바뀌면 워커가 도는 방식도 바뀐다 — 기동 초기화가 몇 번 도는지 다시 셀 것")
    ok("워커 수가 명시돼 있다", workers is not None, cmd.strip()[:120])

    if workers is None:
        return
    # 루트 Dockerfile 의 경고문이 말하는 수와 실제가 같아야 한다
    head = read("Dockerfile")[:1600]
    m = re.search(r"uvicorn\s+--workers\s+(\d+)", head)
    ok("루트 경고문이 적어 둔 워커 수를 찾았다", m is not None)
    if m:
        ok(f"경고문의 수({m.group(1)})가 실제({workers})와 같다", int(m.group(1)) == workers,
           "경고문이 낡으면 그 경고 자체가 다음 오판의 원인이 된다")

    # 워커가 여럿이라는 사실 자체가 기동 잠금의 전제다
    ok("워커가 2개 이상이다 — 기동 백업 잠금이 필요한 이유",
       workers >= 2,
       "1개가 되면 test_backup_lock 의 전제(경합)가 사라진다 — 그때 이 줄을 다시 볼 것")


# ==================================================================
# ④ 이 시험이 배포 게이트에 등록돼 있는가
# ==================================================================
def test_self_registered_in_gate():
    me = os.path.basename(__file__)
    dy = read(".github", "workflows", "deploy.yml")
    ok(f"deploy.yml 이 {me} 를 부른다", me in dy, "만들어 놓고 안 도는 시험이 된다")


if __name__ == "__main__":
    print("=== 배포가 어느 파일을 집어 가는가 회귀 시험 ===")
    test_deploy_builds_from_backend()
    test_dead_files_warn()
    test_backend_dockerfile_is_the_real_one()
    test_self_registered_in_gate()
    print(f"\n통과 {_pass} · 실패 {_fail}")
    sys.exit(1 if _fail else 0)
