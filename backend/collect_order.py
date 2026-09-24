"""수집 순서 — 같은 시간대 안에서 **오래 안 모은 키워드부터** (대표 결정 B · 2026-09-23).

## 왜 바꾸나 — 늘 같은 키워드만 모이고 있었다

`/keywords`(와 중앙 배정 v2 의 claim)는 그 시간대 슬롯의 키워드를 **가나다순**으로 늘어놓고
시간당 상한(시험 상한 10 · 상한 40)에서 자른다. 그래서 매일 **같은 앞쪽 키워드**만 담기고
뒤쪽은 몇 주째 한 번도 안 담긴다.

  9/23 전수조사 실측 — 자동 분석 키워드 591개 중 **131개는 9/9 뒤로 한 번도 안 모였고,
  98개는 한 번도 모인 적이 없다.** 08:30 자동 분석 673건 중 404건이 경쟁 상품 목록 없이 돌았다.

분석이 수집분을 쓰는 창은 **오늘·어제 2일**이다(`collector.serve_from_collected`).
하루 C개를 모으는데 매일 같은 C개면 2일 창에 들어오는 키워드는 C개뿐이다.
오래된 것부터 돌리면 2일 창에 **최대 2C개**가 들어온다 — **수집량(네이버 요청 수)은 그대로다.**

## 규칙

정렬 열쇠 = (오늘 시도했나, 마지막으로 모은 날, 키워드)
  ① 오늘 이미 시도했다 실패한 것은 뒤로 — 종전 규칙 그대로(코덱스 1.22.0 이식).
  ② **한 번도 안 모은 것 → 가장 오래전에 모은 것** 순. (새로 넣은 칸)
  ③ 같으면 가나다순 — 종전과 같은 안정 순서.

⚠️ 슬롯(몇 시에 도는가)·시간당 상한·시험 상한·기계 나누기는 **한 글자도 안 바꾼다.**
   바뀌는 것은 「그 시간대에 누구를 먼저 담나」뿐이다.
⚠️ 「마지막으로 모은 날」은 collected_serp 에 남은 범위(보관 14일)까지만 안다.
   그보다 오래됐거나 한 번도 없으면 똑같이 빈 값 = 맨 앞이다.
⚠️ 조회가 실패하면 빈 dict — 종전 가나다순으로 돌아간다(수집이 멈추는 것보다 낫다).
⚠️ 표준 라이브러리만 — 배포 게이트가 fastapi 없이 import 한다(collect_slot·split_rule 과 같은 이유).
"""

import logging

logger = logging.getLogger(__name__)


def last_collected_map(conn) -> dict:
    """{키워드: 마지막으로 모은 날(YYYY-MM-DD)} — collected_serp 에 남은 범위에서.

    (keyword, collected_date) 유일 색인이 그대로 덮어 주므로 표 본문을 읽지 않는다.
    """
    try:
        return {r[0]: (r[1] or "") for r in conn.execute(
            "SELECT keyword, MAX(collected_date) FROM collected_serp GROUP BY keyword")}
    except Exception as e:
        logger.warning(f"[collector] 마지막 수집일 조회 실패(무시 · 종전 가나다순): {e}")
        return {}


def order_key(keyword: str, attempted: dict = None, last: dict = None):
    """시간대 안 정렬 열쇠 — (오늘 시도, 마지막 수집일, 키워드). 빈 값이 앞선다."""
    return ((attempted or {}).get(keyword, "") or "",
            (last or {}).get(keyword, "") or "",
            keyword)


# ── 🌙 밤 재시도 상한 (대표 확정 2026-09-24 「밤 재시도 횟수 상한은 하루 2번만 해」) ──
#
# 왜 — 9/23 배포 뒤 「같은 키워드를 하루 3번 이상 올린 것」이 0 → 45개가 됐다(9/24 실측).
#   #265 로 밤 시간(23시·0~7시)엔 새로 잴 키워드가 시간당 약 15개로 줄었는데, 기계는 시간당 상한까지 받아 가서
#   남는 몫을 **2페이지에서 막혔던 키워드 재시도**로 채운다. 그래서 「밤엔 적게」가 재시도로 메워져
#   밤에도 두 대가 시간당 약 30건을 불렀다.
# 규칙 — **밤 시간에는**, 오늘 이미 NIGHT_RETRY_DAILY_MAX 번 시도하고도 완료 못 한 키워드를 **다시 주지 않는다.**
#   · 「하루 2번」= 그날 시도 횟수(첫 시도 포함) — 완료(전량·목표 다 찾음)되면 어차피 목록에서 빠진다.
#   · 낮(collect_slot.DAY_HOURS)에는 종전 그대로다(대표 지시가 「밤」이다).
#   · 날짜가 바뀌면(자정) 횟수도 새로 센다 · 다음 날 그 키워드의 슬롯에서 다시 돈다.
#   · 1페이지(40위) 순위는 부분 수집으로 이미 기록돼 있다 — 빠지는 것은 2페이지 이후를 다시 두드리는 몫뿐이다.
# ⚠️ 횟수를 못 세면(조회 실패) 거르지 않는다 — 종전 동작(수집이 멈추는 것보다 낫다).
NIGHT_RETRY_DAILY_MAX = 2


def night_retry_capped(keyword: str, attempts_today: dict, hour: int, day_hours) -> bool:
    """이 시각에 이 키워드를 주지 말아야 하나 — 밤 시간이고 오늘 시도 횟수가 상한에 닿았으면 True."""
    try:
        h = int(hour)
    except Exception:
        return False
    if h in tuple(day_hours or ()):
        return False
    try:
        n = int((attempts_today or {}).get(keyword, 0) or 0)
    except Exception:
        return False
    return n >= NIGHT_RETRY_DAILY_MAX
