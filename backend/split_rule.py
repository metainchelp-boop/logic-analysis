"""여러 대로 나눠 돌릴 때 「이 키워드는 어느 기계 몫인가」를 정하는 규칙.

대표 지시(2026-08-27) — 「1번 기기가 앞쪽, 2번 기기가 뒤쪽을 맡아 겹치지 않게,
중간이 지워져 순번이 당겨져도 누락이 없게」.

⚠️ 왜 파일을 따로 뒀나 (두 가지 다 실제 이유다)
   ① 이 규칙을 쓰는 곳이 **둘**이다 — 순위 목록(/keywords)과 밀린 요청 큐(/requests).
      두 곳이 서로 다른 규칙을 쓰면 한쪽은 겹치고 한쪽은 빠진다.
   ② 배포 게이트가 도는 환경에는 fastapi 가 없어 collector.py 를 임포트할 수 없다.
      규칙이 거기 있으면 **검사할 방법이 없다.** 여기는 표준 라이브러리만 쓴다.

⚠️ 등록 순번으로 가르지 않는다. 순번은 중간이 지워지면 뒤가 당겨져 경계가 흔들리고,
   그 순간 어떤 키워드는 두 대가 같이 하고 어떤 키워드는 아무도 안 한다.
   키워드 글자로 가르면 목록이 늘든 줄든 그 문제가 아예 없다.
"""

import zlib


def worker_of(keyword: str, workers: int) -> int:
    """키워드 → 맡을 기계 번호(0-base). 같은 글자면 언제 계산해도 같은 값.

    ⚠️ 시간대 분배(collector._slot_of)와 **다른 해시**를 쓴다. 같은 값을 두 번
       나누면(예: %15 와 %2) 어느 기계에 특정 시간대가 몰리는 편향이 생길 수 있다.
    """
    if workers <= 1:
        return 0
    return zlib.crc32((keyword + "|worker").encode("utf-8")) % workers


def split_ok(keyword: str, worker: int, workers: int) -> bool:
    """이 기계가 맡을 키워드인가.

    대수를 안 주면(workers<=1) 전부 맡는다 — 지금 도는 1대는 아무것도 안 바뀐다.
    """
    if workers <= 1:
        return True
    return worker_of(keyword, workers) == worker


def normalize(worker, workers):
    """사람이 잘못 넣은 값을 안전한 범위로 — 수집이 통째로 멈추는 것보다 낫다."""
    wc = max(1, int(workers or 1))
    w = max(0, int(worker or 0))
    if w >= wc:
        w = 0
    return w, wc
