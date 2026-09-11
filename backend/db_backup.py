"""DB 백업의 검증·보관 규칙 — 표준 라이브러리만 쓴다.

⚠️ **왜 scheduler.py 에서 떼어냈나**
   배포 회귀 게이트 환경에는 fastapi·apscheduler 가 없다. scheduler.py 를 import 하는
   시험은 그 환경에서 돌지 않는다. 그래서 판단 규칙만 여기로 옮겨 시험 가능하게 했다.
   (split_rule.py·keyword_mute.py·sbiz_health.py·tracking_eligibility.py 와 같은 이유·같은 방식.)

⚠️ **이 파일이 생긴 경위 — 실측으로 잡은 사고 (2026-09-11)**
   9/11 00:30 백업의 압축본이 **9.0% 지점에서 끊겨 있었다**(EOFError, 243MB/2.7GB).
   00:29 에 나간 배포가 컨테이너를 00:31:23 에 교체하면서 gzip 프로세스를 죽인 것이다.
   그런데 백업 로그에는 그런 흔적이 없었다 — 압축이 **끝났는지 아무도 안 봤기 때문**이다.
   같은 이유로 `os.remove(원본)` 도 못 돌아 비압축본 2.6GB 가 남았고, **그 사고가
   유일하게 쓸 수 있는 백업을 남겨 준 셈**이 됐다. 운에 맡길 일이 아니다.

   ⭐ 교훈 — 「백업을 만들었다」와 「그 백업으로 되돌릴 수 있다」는 다른 축이다.
      만든 것만 로그에 적고 풀리는지 안 보면, 필요한 날에야 알게 된다.
"""

import gzip
import os
import zlib

# 한 세대(백업 1회)는 파일이 2개일 수 있다 — 압축본 + (압축이 끊겼을 때 남는) 비압축본.
_PREFIX = "logic_analysis_backup_"
_SUFFIXES = (".db", ".db.gz")


def generation_of(filename):
    """파일명에서 세대 키(타임스탬프)를 뽑는다. 백업 파일이 아니면 None.

    `logic_analysis_backup_20260911_003000.db`    → '20260911_003000'
    `logic_analysis_backup_20260911_003000.db.gz` → '20260911_003000'  (같은 세대)
    """
    if not filename.startswith(_PREFIX):
        return None
    if not filename.endswith(_SUFFIXES):
        return None
    return filename[len(_PREFIX):].split(".db")[0] or None


def plan_prune(filenames, keep):
    """지울 파일 목록을 돌려준다 — **세대 단위**로 센다.

    ⚠️ **종전 결함**: 「파일 개수」로 세어 `keep=2` 에 파일 2개면 정리가 멈췄다.
       압축이 끊겨 `.db` 가 남은 날에는 **그 하루가 보관 2세대를 통째로 차지**했고,
       지난 세대가 밀려났다. 9/11 실측 「파일 2개 · 실제 보관 세대 1개」가 그 결과다.
       ⇒ 세대로 세고, 한 세대의 파일은 함께 남기거나 함께 지운다.

    세대 키가 `YYYYMMDD_HHMMSS` 라 문자열 정렬 = 시간 정렬이다.
    """
    if keep is None or keep < 0:
        keep = 0
    gens = {}
    for f in filenames:
        g = generation_of(f)
        if g:
            gens.setdefault(g, []).append(f)
    order = sorted(gens)
    drop = order[:-keep] if keep else order
    out = []
    for g in drop:
        out.extend(sorted(gens[g]))
    return out


def verify_gzip(gz_path, expect_bytes=None, chunk=8 * 1024 * 1024):
    """압축본을 **끝까지 풀어** 쓸 수 있는지 본다. 디스크에 쓰지 않는다.

    돌려주는 값: ``(ok, n, reason)``
      ok     — 끝까지 풀리고(필요하면 크기까지 맞고) 복구에 쓸 수 있는가
      n      — 실제로 풀린 바이트 수
      reason — ok 가 False 인 이유(사람이 읽는 한 줄). ok 면 None

    ⚠️ 크기 비교를 넣은 이유 — 끊긴 gzip 이 **예외 없이** 끝나는 경우가 있다
       (마지막 블록 경계에서 잘리면 EOF 로 읽힌다). 「예외가 안 났다」만으로
       성공을 판정하면 그 경우를 놓친다. 원본 크기를 알면 그것까지 본다.
    ⚠️ 2.6GB 를 파일로 풀면 디스크를 채워 앱의 DB 쓰기를 막는다(2026-07-20 실사고).
       그래서 스트림으로 읽어 바이트만 센다.
    """
    n = 0
    try:
        with gzip.open(gz_path, "rb") as g:
            while True:
                b = g.read(chunk)
                if not b:
                    break
                n += len(b)
    except (EOFError, OSError, zlib.error) as e:
        return False, n, f"{type(e).__name__}: {str(e)[:120]}"

    if expect_bytes:
        if n != expect_bytes:
            pct = (100.0 * n / expect_bytes) if expect_bytes else 0.0
            return False, n, (f"푼 크기가 원본과 다르다 — {n:,} / {expect_bytes:,} "
                              f"({pct:.1f}%)")
    elif n == 0:
        return False, 0, "푼 내용이 0바이트다"
    return True, n, None


def keep_raw_reason(ok, reason):
    """압축본을 버리고 **비압축 원본을 남겨야 하는가** — 로그에 적을 한 줄.

    압축이 깨졌으면 원본이 그날의 유일한 백업이다. 지우면 복구 수단이 사라진다.
    """
    if ok:
        return None
    return (f"압축본을 버리고 비압축 원본을 백업으로 남긴다 — {reason}. "
            f"⚠️ 다음 배포가 00:30 백업과 겹치면 같은 일이 반복된다.")
