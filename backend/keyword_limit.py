"""추적 키워드 개수 상한 — 규칙 한 곳.

## 왜 상한이 필요한가 (대표 확정 2026-09-18)

대표 지시 원문: 「거기에 키워드 추가는 최대 5개까지만 가능하게 제한을 두도록 해.」

순위 추적은 광고주에게 파는 상품 서비스다. 한 업체가 키워드를 무제한으로 넣으면
수집 총량이 그만큼 늘고, 그 부담은 **네이버로 나가는 요청**으로 그대로 간다.
2026-09-09 에 수집이 통째로 막힌 원인 축이 그것이었다.

## 무엇에 거는 상한인가

**사람이 손으로 추가하는 경로**에만 건다.
업체 대표 키워드와 「추적하기로 한」 키워드가 자동으로 들어오는 것은 이 상한 밖이다
(대표 지시: 「대표 키워드, 추적 하기로한 키워드는 자동으로 등록되도록 하고,
거기서 더 추가하고 싶은 경우 … 별도로 키워드를 최대 5개까지 등록을 허용」).

⚠️ **지금 구현은 「상품 1개당 5개」다.** 대표 지시의 「업체당 5개」와 다를 수 있어
   대표께 확인을 요청해 두었다. 업체 단위로 바꾸려면 `count_for_client` 를 쓰는
   갈래만 갈아 끼우면 된다 — 상한 값과 판정 자리는 여기 한 곳에 모아 두었다.

## 왜 파일을 따로 뒀나 (split_rule.py · collect_slot.py 와 같은 이유)

① 쓰는 곳이 **둘 이상**이다 — 등록 API 와 화면 안내. 두 곳이 다른 수를 쓰면
   화면은 「5개까지」라고 하는데 서버가 3개에서 막는 일이 생긴다.
② 배포 회귀 게이트 환경에는 fastapi 가 없어 main.py·database.py 를 import 할 수 없다.
   규칙이 거기 있으면 **검사할 방법이 없다.** 여기는 표준 라이브러리만 쓴다.
"""

import sqlite3

# 사람이 손으로 더 넣을 수 있는 키워드 수 (대표 확정 2026-09-18)
MAX_MANUAL_KEYWORDS = 5

LIMIT_MESSAGE = (
    f"키워드는 최대 {MAX_MANUAL_KEYWORDS}개까지 추가할 수 있습니다. "
    "더 넣으시려면 쓰지 않는 키워드를 먼저 빼 주세요."
)


def count_for_product(conn, product_id) -> int:
    """이 상품에 이미 달려 있는 키워드 수. 조회가 실패하면 -1."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM tracked_keywords WHERE product_id = ?",
            (product_id,)).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return -1


def count_for_client(conn, client_id) -> int:
    """이 업체에 이어진 추적 상품 전체의 키워드 수(중복 제거). 실패하면 -1.

    ⚠️ 지금은 쓰지 않는다 — 「업체당 5개」로 확정되면 이쪽으로 갈아 끼운다.
       미리 만들어 두는 이유는, 갈아 끼울 때 세는 식을 새로 쓰지 않기 위해서다.
    """
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT k.keyword) FROM tracked_keywords k"
            "  JOIN rank_link l ON l.tracked_product_id = k.product_id"
            " WHERE l.client_id = ?", (client_id,)).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return -1


def can_add(current_count: int, adding: int = 1) -> bool:
    """지금 n개인데 adding개를 더 넣어도 되나.

    ⚠️ `current_count < 0` 은 **세는 데 실패한 것**이다. 그때는 막지 않는다 —
       조회 하나가 실패했다고 등록이 통째로 안 되는 쪽이 훨씬 나쁘다
       (이 저장소가 여러 번 택한 fail-open 원칙).
    """
    try:
        cur = int(current_count)
        add = max(0, int(adding))
    except (TypeError, ValueError):
        return True
    if cur < 0:
        return True
    return cur + add <= MAX_MANUAL_KEYWORDS


def remaining(current_count: int) -> int:
    """앞으로 몇 개 더 넣을 수 있나(화면 안내용). 못 세면 상한을 그대로 돌려준다."""
    try:
        cur = int(current_count)
    except (TypeError, ValueError):
        return MAX_MANUAL_KEYWORDS
    if cur < 0:
        return MAX_MANUAL_KEYWORDS
    return max(0, MAX_MANUAL_KEYWORDS - cur)
