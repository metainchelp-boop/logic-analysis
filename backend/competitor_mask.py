"""경쟁사 상호 가리기 — 숫자는 그대로, 이름만 「경쟁사 A」로.

대표 확정 2026-08-31 — 광고주가 분석 보고서 전문을 그대로 열람하게 되면서
「경쟁사 실명도 일부 가리는 걸로」 · 「상호만 가리고 숫자는 유지」 · 「저장할 때부터 가림」.

⭐ 한 곳에서만 가린다.
   실명은 경쟁사 비교표(상품명·스토어·브랜드)뿐 아니라 진입 전략의 「주요 브랜드」·추천 문구
   에도 흩어져 있다. 섹션마다 손대면 새 섹션이 생길 때마다 구멍이 난다. 그래서
   **분석 딕셔너리의 문자열 값 전체**에 사전을 한 번 적용한다.

⚠️ 숫자·순위·가격·검색량은 손대지 않는다 — 그것이 보고서의 값어치다.
⚠️ 광고주 본인 업체명은 절대 가리지 않는다(자기 상품이 어느 줄인지 못 찾게 된다).
⚠️ 두 글자 미만 이름은 건너뛴다 — 흔한 글자가 본문 곳곳에서 잘못 바뀐다.
⚠️ 긴 이름부터 바꾼다 — 「사미헌」을 먼저 바꾸면 「사미헌몰」이 「경쟁사A몰」로 깨진다.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

# 사전에서 제외할 값 — 이름이 아니거나 너무 흔해 오탐을 낸다.
_SKIP = {"", "-", "none", "null", "기타", "미상", "정보없음"}

# 「경쟁사 A」… 「경쟁사 Z」 이후는 「경쟁사 AA」 식으로 이어 붙인다.
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _alias(index: int) -> str:
    """0→A, 25→Z, 26→AA …"""
    name = ""
    i = index
    while True:
        name = _LETTERS[i % 26] + name
        i = i // 26 - 1
        if i < 0:
            break
    return f"경쟁사 {name}"


def _normalize(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_alias_map(analysis: Dict[str, Any], company_name: str = "") -> Dict[str, str]:
    """경쟁사 상호 사전을 만든다 — **한 회사는 한 별칭**.

    ⚠️ 같은 회사가 스토어명과 브랜드명으로 두 번 나온다(「사미헌몰」·「사미헌」).
       각각 다른 별칭을 주면 「경쟁사 B 맑은 곰탕을 경쟁사 A 가 판다」처럼 읽혀
       한 회사가 둘로 보인다. 그래서 **같은 줄의 스토어·브랜드는 한 별칭을 쓴다.**

    번호는 표에 나온 차례(=순위)를 따른다 — 1위가 「경쟁사 A」다.
    """
    own = _normalize(company_name)
    alias_map: Dict[str, str] = {}
    next_index = 0

    def usable(value: str) -> bool:
        if len(value) < 2 or value.lower() in _SKIP:
            return False
        # 광고주 본인은 가리지 않는다 — 서로 포함관계여도 본인으로 본다.
        return not (own and (value == own or value in own or own in value))

    for row in analysis.get("competitorTable") or []:
        if not isinstance(row, dict):
            continue
        group = [v for v in (_normalize(row.get("store")), _normalize(row.get("brand"))) if usable(v)]
        if not group:
            continue
        # 이 줄의 이름 중 하나라도 이미 사전에 있으면 그 별칭을 함께 쓴다.
        alias = next((alias_map[v] for v in group if v in alias_map), None)
        if alias is None:
            alias = _alias(next_index)
            next_index += 1
        for value in group:
            alias_map.setdefault(value, alias)

    # 표에 없고 문구에만 나오는 브랜드(진입 전략의 「주요 브랜드」)도 사전에 넣는다.
    # ⚠️ 이걸 빼면 표는 가려졌는데 문구에 실명이 남는다 — 가장 눈에 띄는 자리다.
    extra = _normalize((analysis.get("strategicAnalysis") or {}).get("mainBrands"))
    for token in re.split(r"[,·/|]", extra):
        value = token.strip()
        if usable(value) and value not in alias_map:
            alias_map[value] = _alias(next_index)
            next_index += 1

    return alias_map


def mask_text(text: str, alias_map: Dict[str, str]) -> str:
    """문자열 하나에 사전을 적용. 긴 이름부터 바꾼다."""
    if not text or not alias_map:
        return text
    for name in sorted(alias_map, key=len, reverse=True):
        if name in text:
            text = text.replace(name, alias_map[name])
    return text


def _mask_value(value: Any, alias_map: Dict[str, str]) -> Any:
    if isinstance(value, str):
        return mask_text(value, alias_map)
    if isinstance(value, dict):
        return {k: _mask_value(v, alias_map) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v, alias_map) for v in value]
    # 숫자·불리언·None 은 그대로 — 손대지 않는다.
    return value


def mask_analysis(analysis: Dict[str, Any], company_name: str = "") -> Dict[str, Any]:
    """분석 딕셔너리의 **사본**을 돌려준다(원본 무접촉).

    호출부가 원본을 그대로 저장하고 싶을 수 있으므로 절대 제자리에서 고치지 않는다.
    """
    if not isinstance(analysis, dict):
        return analysis
    alias_map = build_alias_map(analysis, company_name)
    if not alias_map:
        return copy.deepcopy(analysis)
    return _mask_value(copy.deepcopy(analysis), alias_map)


def mask_html(html: str, alias_map: Dict[str, str]) -> str:
    """이미 만들어진 보고서 HTML 에 사전을 적용한다(옛 보고서용).

    ⚠️ 태그·속성까지 함께 바뀔 수 있으므로 **본문 텍스트에만** 쓴다는 전제다.
    상호가 클래스명·URL 에 들어가는 경우는 이 저장소에 없다(확인함).
    """
    return mask_text(html, alias_map)
