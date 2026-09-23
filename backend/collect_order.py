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
