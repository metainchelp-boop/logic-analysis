"""수집 시험 상한 — 재개할 때 **키워드 1개씩만** 내보내는 스위치 (2026-09-15 대표 확정)

왜 있나
  9/12 이후 3일을 쉬고 v1.11.0(클릭으로 넘기기)을 처음 실전에 건다. 그런데 「키워드 1개만」
  돌리는 장치가 없어, 켜는 순간 첫 회차가 시간대 몫 최대 40개 + 온디맨드 12개를 바로 돈다.
  막히면 요청 수십 건이 한 번에 나가 IP 가 또 탄다(8/28·9/12 반복). 그래서 서버가 내보내는
  양을 여기서 묶는다 — 확장 코드는 한 줄도 안 바꾼다(확장은 서버가 주는 만큼만 돈다).

어떻게 켜고 끄나
  DEFAULT_TEST_CAP 이 기본값이고, 서버 .env 의 COLLECT_TEST_CAP 이 있으면 그 값이 이긴다.
  · 0  = 평소 운행(상한 없음)
  · n>0 = 시간대 회차마다 최대 n개 · 온디맨드는 0개
  ⚠️ 켜고 끄는 손은 PR + 배포다(서버 SSH 불필요). 시험이 끝나면 DEFAULT_TEST_CAP 을 0 으로
     되돌리는 PR 을 낸다 — 잊으면 하루 24개밖에 못 모은다(그래서 응답에 test_cap 을 실어
     팝업 로그에서 바로 보이게 한다).

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi 가 없다 — collector.py 는 게이트에서 import 불가라
   이 규칙을 따로 뺐다. split_rule.py 와 같은 이유).
"""
import os

# ⚠️ 이 값이 곧 운행 모드다. n>0 = 시험(회차당 n개 · 온디맨드 0). 0 = 평소(상한 없음).
#
# 2026-09-18 대표 지시 「한시간에 1개씩이면 너무 작업량이 적지 않아? 최소 10분에 1개씩」 → **1 → 5**.
#   실측 근거: 오늘 회차 간격이 12:32 → 12:46 → 13:01 로 **한 키워드에 10~14분**이다
#   (10페이지를 넘기며 페이지마다 기다린다). 그래서 회차당 5개면 정시에 연속 처리되어
#   **실질 10~12분에 1개** — 대표가 말한 속도와 같아진다.
#   ⇒ 하루 120개 · 요청 약 1,200건/일. 9/9 에 막힌 부하(약 12,000건/일)의 **1/10** 이다.
# ⚠️ 유니버스 1,219개라 이 속도로는 **한 바퀴에 10일**이다. 종전(하루 1,088개)에 한참 못 미친다.
#    다음 단계(키워드별 nvMid 목록을 내려 **다 찾으면 조기 종료** + 깊이 300위)가 들어가면
#    같은 요청 예산으로 2~3배를 돌 수 있다 — 그때 이 값을 다시 올린다.
DEFAULT_TEST_CAP = 10

ENV_KEY = "COLLECT_TEST_CAP"


def effective_cap(env=None) -> int:
    """지금 적용되는 상한. env 값이 있으면 그것, 없거나 못 읽으면 DEFAULT_TEST_CAP.
    음수·문자열 쓰레기는 기본값으로 떨어뜨린다(잘못 적어도 평소보다 위험해지지 않게)."""
    src = os.environ if env is None else env
    raw = src.get(ENV_KEY)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_TEST_CAP
    try:
        v = int(str(raw).strip())
    except ValueError:
        return DEFAULT_TEST_CAP
    return v if v >= 0 else DEFAULT_TEST_CAP


def apply_cap(keywords, cap: int):
    """시간대 몫에 상한을 건다. cap<=0 이면 그대로."""
    if cap is None or cap <= 0:
        return list(keywords)
    return list(keywords)[:cap]


def ondemand_allowed(cap: int) -> bool:
    """시험 중에는 온디맨드를 내보내지 않는다 — 시험은 「사람이 고른 1개」가 아니라
    「서버가 정한 1개」로 해야 회차가 예측 가능하다."""
    return not (cap and cap > 0)
