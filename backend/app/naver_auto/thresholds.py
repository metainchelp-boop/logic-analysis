"""점검 기준값 — 처음 값 · 허용 범위 (설계 v1.7 점검 표 · v1.8 Q3 「2차에서 고치는 사람 = 대표만」).

범위 밖 값은 저장하지 않는다(``validate`` 가 거절). 누가 고칠 수 있는지는 화면 API(S11)가 ``scope`` 로 판정한다.
순수 모듈 — 저장·네트워크를 모른다.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Mapping


class ThresholdOutOfRange(ValueError):
    """허용 범위 밖 · 모르는 이름 · 서로 맞지 않는 값. 문구에는 칸 이름만."""


@dataclass(frozen=True)
class Thresholds:
    bizmoney_red_days: float = 1.0       # 잔액 ÷ 하루 평균 광고비가 이보다 작으면 🔴
    bizmoney_yellow_days: float = 3.0    # 이보다 작으면 🟡
    jump_up_ratio: float = 2.0           # 같은 요일 4주 평균의 이 배 이상이면 급증
    jump_down_ratio: float = 0.5         # 이 배 이하면 급감
    jump_min_spend: int = 10000          # 기준과 어제가 둘 다 이보다 작으면 급변을 보지 않는다(원)
    jump_min_weeks: int = 3              # 같은 요일 4주 중 이만큼은 자료가 있어야 기준이 된다
    stage_stale_hours: int = 26          # 전산 단계 자료가 이보다 낡으면 단계·광고비 규칙을 돌리지 않는다
    zero_spend_days: int = 3             # 진행중인데 최근 이 날수 광고비 합계가 0 이면 🟡
    period_end_days: int = 3             # 캠페인 기간이 이 날수 안에 끝나면 ⓘ


# 이름 → (가장 작은 값, 가장 큰 값)
RANGES = {
    "bizmoney_red_days": (0.5, 3.0),
    "bizmoney_yellow_days": (1.0, 14.0),
    "jump_up_ratio": (1.2, 10.0),
    "jump_down_ratio": (0.05, 0.9),
    "jump_min_spend": (0, 1_000_000),
    "jump_min_weeks": (2, 4),
    "stage_stale_hours": (12, 72),   # 최소 12 — 단계 동기화 6시간 + 실패 뒤 1시간 + 조용한 창 여유(S7 · 엔진 시험이 대조)
    "zero_spend_days": (1, 14),
    "period_end_days": (0, 14),
}
_INTS = frozenset({"jump_min_spend", "jump_min_weeks", "stage_stale_hours", "zero_spend_days", "period_end_days"})

DEFAULTS = Thresholds()


def validate(changes: Mapping[str, object], base: Thresholds = DEFAULTS) -> Thresholds:
    """바꿀 값만 받아 새 기준값을 만든다. 하나라도 틀리면 아무것도 바꾸지 않고 ``ThresholdOutOfRange``."""
    names = {f.name for f in fields(Thresholds)}
    bad = []
    clean = {}
    for k, v in changes.items():
        if k not in names:
            bad.append(k)
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:  # 참·거짓 · 숫자 아님 · NaN
            bad.append(k)
            continue
        if k in _INTS and not float(v).is_integer():
            bad.append(k)
            continue
        lo, hi = RANGES[k]
        if not (lo <= v <= hi):
            bad.append(k)
            continue
        clean[k] = int(v) if k in _INTS else float(v)
    if bad:
        raise ThresholdOutOfRange("허용 범위 밖이거나 모르는 기준값: " + ", ".join(sorted(map(str, bad))))
    out = replace(base, **clean)
    if not out.bizmoney_red_days < out.bizmoney_yellow_days:
        raise ThresholdOutOfRange("비즈머니 🔴 날수는 🟡 날수보다 작아야 한다")
    return out
