"""S0 — 다른 사이트 화면이 ③ API 를 부르는 것(CORS)을 기본으로 막는다.

예전: 모든 사이트(*)에 모든 방식·머리를 열어 두었다. 전 저장소를 찾아봐도 ③ API 를 다른 사이트 화면에서 부르는 곳은 0
(전산은 새 창 ``?sso=`` 로 연다 · 네이버 관제 화면은 같은 주소) ⇒ 기본 = 아무 곳에도 열지 않는다.
꼭 열어야 하면 환경 ``CORS_ALLOW_ORIGINS`` 에 정확한 주소만 쉼표로(``https://이름.metainc.co.kr``) — ``*``·경로·틀린 모양은 버린다.
표준 라이브러리만.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

_ORIGIN = re.compile(r"https?://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:(?P<port>[0-9]{1,5}))?")


def allowed_origins(raw: Optional[str]) -> Tuple[List[str], int]:
    """(열어 줄 주소 목록, 버린 개수). 대소문자는 작은 글자로 · 같은 것은 한 번."""
    out: List[str] = []
    dropped = 0
    for part in (raw or "").split(","):
        o = part.strip().lower().rstrip("/")
        if not o:
            continue
        m = _ORIGIN.fullmatch(o)
        port = m.group("port") if m else None
        if m and (port is None or 0 < int(port) < 65536):
            if o not in out:
                out.append(o)
        else:
            dropped += 1
    return out, dropped
