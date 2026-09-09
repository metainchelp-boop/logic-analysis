#!/usr/bin/env python3
"""
죽은 쇼핑 API 차단기 시험 — 표준 라이브러리만 (2026-09-09)

## 왜 이 시험이 있나
네이버 쇼핑 검색 API 는 2026-07-31 에 종료됐다(404 SE05). 그런데 08:00 순위 배치는
수집분이 없는 키워드마다 그것을 계속 부르고, **실패 자리에서 조건 없이 18초를 쉬었다.**
실측(2026-09-08): 861개 중 661개가 그 경로 → 661 × 18초 = 3.3시간.
배치가 08:00~11:52(3시간 52분) 걸려 전산①이 08:40 에 가져갈 때 완료율이 10~12% 였다.
(04:30 스케줄이던 7월엔 77~89% 였다.)

⚠️ 2026-08-05 수정이 **성공 경로의 대기만 고치고 실패 경로를 빠뜨린 것**이 직접 원인이다.

## 어떻게 검사하나
배포 게이트에는 fastapi 가 없어 scheduler.py 를 임포트할 수 없다.
그래서 ① 상수와 코드 표식을 **실제 소스에서 뽑아** 확인하고,
② 같은 모양의 루프를 돌려 실측 규모(861/661)에서 걸리는 시간을 계산한다.
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHED = os.path.join(HERE, "..", "scheduler.py")
CRAWLER = os.path.join(HERE, "..", "naver_crawler.py")

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILED.append(name)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def const(src, name):
    """소스에서 상수 값을 뽑는다 — 시험이 실제 코드의 숫자를 쓰게."""
    m = re.search(rf"^\s*{name}\s*=\s*([0-9.]+)", src, re.M)
    assert m, f"{name} 을 소스에서 못 찾았다"
    return float(m.group(1))


def simulate(total, dead, delay_keyword, delay_collected, pages, delay_page, breaker_after):
    """배치 루프의 대기 시간만 흉내 낸다(네트워크 시간 제외).

    수집분 있는 키워드 = 네이버 미호출 → 짧은 양보.
    수집분 없는 키워드 = 차단기가 켜지기 전까지만 호출하고, 그 뒤로는 호출도 대기도 없다.
    """
    seconds = 0.0
    calls = 0
    api_dead = False
    streak = 0
    for i in range(total):
        is_dead_kw = i < dead          # 최악 배치: 죽은 키워드가 앞에 몰린 경우
        naver_called = False
        if is_dead_kw and not api_dead:
            calls += 1                 # 404 는 1페이지에서 끊긴다
            naver_called = True
            streak += 1
            if streak >= breaker_after:
                api_dead = True
        seconds += delay_keyword if naver_called else delay_collected
    return seconds, calls


def main():
    print("죽은 API 차단기 시험")
    s = read(SCHED)
    c = read(CRAWLER)

    # ① 소스 표식
    check("① 404 응답에 기계용 표식이 붙는다", '"apiRetired": True' in c)
    check("① 배치가 그 표식을 읽는다", 'shop_result.get("apiRetired")' in s)
    check("① 차단기 상태 변수가 있다", "_api_dead = False" in s and "_api_dead_streak = 0" in s)
    check("① 차단기가 켜지면 페이지 루프에 안 들어간다",
          "_pages = 0 if (all_prods or _api_dead) else RANK_PAGES" in s)
    check("① 건너뛴 수를 완료 로그에 남긴다", "죽은 API 건너뜀" in s)

    # ② 실패 자리의 대기 — 이 시험의 핵심
    fail_block = s[s.index("if not all_prods:"):]
    fail_block = fail_block[:fail_block.index("continue")]
    check("② 실패 자리가 조건 없이 18초를 쉬지 않는다",
          "time.sleep(DELAY_PER_KEYWORD)" not in fail_block,
          "조건 없는 DELAY_PER_KEYWORD 가 남아 있다 — 2026-08-05 에 빠뜨린 그 자리다")
    check("② 실패 자리도 「실제로 불렀을 때만」 쉰다",
          "time.sleep(DELAY_PER_KEYWORD if _naver_called else DELAY_COLLECTED)" in fail_block)
    check("② 성공 자리는 종전 그대로(무회귀)",
          s.count("time.sleep(DELAY_PER_KEYWORD if _naver_called else DELAY_COLLECTED)") == 2)

    # ③ 로그 도배 방지
    check("③ 실패 줄을 앞 10건만 남긴다", "if total_errors <= 10:" in s)
    check("③ 접었다는 것을 한 번 알린다", "개별 줄은 접는다" in s)

    # ④ 실측 규모로 걸리는 시간
    dk = const(s, "DELAY_PER_KEYWORD")
    dc = const(s, "DELAY_COLLECTED")
    dp = const(s, "DELAY_PER_PAGE")
    pages = const(s, "RANK_PAGES")
    after = const(s, "API_DEAD_AFTER")
    check("④ 상수를 소스에서 읽었다", (dk, dc, pages) == (18.0, 0.2, 3.0),
          f"dk={dk} dc={dc} pages={pages}")

    TOTAL, DEAD = 861, 661          # 2026-09-08 실측
    before, _ = simulate(TOTAL, DEAD, dk, dc, pages, dp, breaker_after=10**9)  # 차단기 없음
    after_s, calls = simulate(TOTAL, DEAD, dk, dc, pages, dp, breaker_after=after)

    print(f"       고치기 전: {before/3600:.2f}시간 · 죽은 API 호출 {DEAD}회")
    print(f"       고친 뒤  : {after_s/60:.1f}분 · 죽은 API 호출 {calls}회")

    check("④ 고치기 전은 3시간을 넘는다(실측 3시간 52분과 맞는다)", before > 3 * 3600,
          f"{before/3600:.2f}시간")
    check("④ 고친 뒤는 10분 안쪽이다", after_s < 10 * 60, f"{after_s/60:.1f}분")
    check("④ 08:35 안에 끝난다(전산① 08:40 계약)", after_s < 35 * 60, f"{after_s/60:.1f}분")
    check(f"④ 죽은 API 호출이 {int(after)}회로 줄어든다", calls == int(after), f"실제 {calls}회")

    # ⑤ 무회귀 — 수집분이 다 있는 정상적인 날
    normal, ncalls = simulate(TOTAL, 0, dk, dc, pages, dp, breaker_after=after)
    check("⑤ 수집분이 다 있으면 네이버를 한 번도 안 부른다", ncalls == 0)
    check("⑤ 그날은 3분 안쪽", normal < 180, f"{normal:.0f}초")

    # ⑥ API 가 되살아나면 스스로 복구되는가 (회차마다 초기화)
    check("⑥ 차단기가 함수 안에서 매번 초기화된다",
          s.index("_api_dead = False") > s.index("def _run_rank_tracking"),
          "전역이면 API 가 살아나도 영영 안 부른다")
    check("⑥ 살아 있는 응답이 오면 연속 횟수가 풀린다",
          'if shop_result.get("items"):' in s and "_api_dead_streak = 0" in s)

    print()
    if FAILED:
        print(f"❌ 실패 {len(FAILED)}건: {FAILED}")
        return 1
    print("죽은 API 차단기 시험 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
