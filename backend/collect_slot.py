"""키워드가 하루 중 **몇 시에 수집되는가** — 그 규칙 한 곳.

## 왜 시간대로 나누나

한 IP 에서 짧은 시간에 몰아 치면 네이버가 막는다(2026-08-05 실사고 — 6시간에 3,800여 회로
IP 차단). 그래서 수집을 24시간에 흩뿌리고, 키워드마다 **글자에서 계산한 고정 슬롯**을 준다.
같은 키워드는 언제나 같은 시각에 돈다(안정 해시).

## 왜 두 몫으로 가르나

업체 대표 키워드·분석 이력은 앞쪽(0~14시), 추적 상품에만 등록된 키워드는 뒤쪽(15~23시)이다.
하루 처리량이 유한하므로, 우선순위가 있는 것을 먼저 돌린다.

⚠️ **그래서 추가로 등록한 추적 키워드는 오후가 돼야 처음 기록된다.**
   이걸 화면이 안 알려 주면 직원은 「등록했는데 아무 일도 안 일어난다」로 읽는다 —
   실제로 그렇게 신고가 들어왔다(#248, 2026-08-31). 화면이 예상 시각을 말해 줘야 한다.

## 왜 파일을 따로 뒀나 (split_rule.py 와 같은 이유)

① 쓰는 곳이 **둘**이다 — 수집 배분(collector)과 화면의 「언제 수집되나」 안내(client_dashboard).
   두 곳이 다른 식을 쓰면 화면이 거짓말을 한다.
② 배포 게이트 환경에 fastapi 가 없어 collector.py 를 임포트할 수 없다.
   규칙이 거기 있으면 **검사할 방법이 없다.** 여기는 표준 라이브러리만 쓴다.
"""

import zlib

PRIORITY_HOURS = 15                 # 업체 키워드 슬롯 = 0~14시
LATE_HOURS = 24 - PRIORITY_HOURS    # 나머지(추적 상품 전용) = 15~23시


def slot_of(keyword: str, priority: bool) -> int:
    """키워드 → 수집 시간대(0~23). 문자열이 같으면 항상 같은 값(안정 해시).

    ⚠️ 이 식을 바꾸면 **모든 키워드의 수집 시각이 한꺼번에 이동한다.**
       그날 하루는 이미 지나간 슬롯으로 재배정된 키워드가 통째로 밀린다.
    """
    h = zlib.crc32((keyword or "").encode("utf-8"))
    if priority:
        return h % PRIORITY_HOURS
    return PRIORITY_HOURS + (h % LATE_HOURS)


def slot_label(hour: int) -> str:
    """사람이 읽는 시각 — 「오후 5시경」.

    ⚠️ 「몇 분」까지 말하지 않는다. 슬롯은 그 시간대 안에서 순서가 정해지고,
       앞 시간대가 밀리면 뒤로 미뤄지기도 한다. 지킬 수 없는 약속은 하지 않는다.
    """
    try:
        h = int(hour)
    except Exception:
        return ""
    h %= 24
    if h == 0:
        return "자정 무렵"
    if h < 12:
        return f"오전 {h}시경"
    if h == 12:
        return "정오 무렵"
    if h < 18:
        return f"오후 {h - 12}시경"
    return f"밤 {h - 12}시경"


def wait_hint(keyword: str, priority: bool, now_hour=None) -> str:
    """「오후 5시경 수집」처럼 화면에 그대로 쓸 한 줄.

    이미 그 시각이 지났으면 「오늘 안에 수집」으로 바꾼다 — 지난 시각을 앞으로 올 것처럼
    적으면 그게 더 헷갈린다(밀린 것은 그날 안에 따라잡는 구조다).
    """
    s = slot_of(keyword, priority)
    if now_hour is not None:
        try:
            if int(now_hour) > s:
                return "오늘 안에 수집"
        except Exception:
            pass
    return f"{slot_label(s)} 수집"
