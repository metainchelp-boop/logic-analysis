"""대행사 키 3종 — 환경변수에서 한 번만 읽고, 값이 새지 않게 감싼다.

환경변수 이름(값은 엔진 전용 ``.env`` 에만 · 대표가 직접 넣는다 · 채팅·저장소 금지):
  NAVER_MGR_CUSTOMER_ID  대행사 계정 고객 번호
  NAVER_MGR_API_KEY      액세스 라이선스
  NAVER_MGR_SECRET_KEY   비밀키

⚠️ 표준 라이브러리 ``secrets`` 와 헷갈리지 않게 이 파일 이름은 ``credentials`` 로 했다(계획서의 ``secrets.py``).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional

ENV_CUSTOMER_ID = "NAVER_MGR_CUSTOMER_ID"
ENV_API_KEY = "NAVER_MGR_API_KEY"
ENV_SECRET_KEY = "NAVER_MGR_SECRET_KEY"

_MASK = "Secret(****)"
_DIGITS = re.compile(r"[0-9]{1,15}")
_KEY_CHARS = re.compile(r"[\x21-\x7e]{8,512}")  # 눈에 보이는 영문·숫자·기호만(빈칸·줄바꿈·한글 금지)


class CredentialsMissing(RuntimeError):
    """비밀값이 없거나 모양이 틀림. 문구에는 환경변수 **이름**만 들어간다."""


class Secret:
    """값을 감싼다. ``repr``·``str``·``format``·예외 문구에는 가린 글자만 나온다.

    값을 꺼내는 길은 ``reveal()`` 하나뿐이고, 그것을 부르는 곳은 ``naver_read`` 의 요청 만드는 한 곳뿐이다
    (시험 ``test_reveal_only_in_gate`` 가 고정).
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise CredentialsMissing("비밀값이 비어 있습니다")
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        return self._value

    def mac(self, message: bytes) -> bytes:
        """이 값을 열쇠로 한 HMAC-SHA256 — 값을 꺼내지 않고 서명만 만든다(화면 API 자체 토큰 · S11)."""
        if not isinstance(message, (bytes, bytearray)):
            raise TypeError("서명할 글은 bytes 여야 합니다")
        return hmac.new(self._value.encode("utf-8"), bytes(message), hashlib.sha256).digest()

    def bucket_key(self) -> str:
        """같은 값끼리만 같은 글자(SHA-256 앞 32자) — 로그인 되풀이를 토큰마다 세는 열쇠(S12 검토).
        이 프로세스 기억 안에서만 쓴다 · 저장·기록·응답에 싣지 않는다."""
        return hashlib.sha256(self._value.encode("utf-8")).hexdigest()[:32]

    def __setattr__(self, name, value):  # 한 번 만들면 못 바꾼다
        raise AttributeError("Secret 은 바꿀 수 없습니다")

    def __repr__(self) -> str:
        return _MASK

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return _MASK

    def __eq__(self, other) -> bool:  # 비교로 값이 새지 않게 — 같은 객체일 때만 같다
        return self is other

    __hash__ = object.__hash__

    def __reduce__(self):  # 피클로 값이 새지 않게
        raise TypeError("Secret 은 직렬화할 수 없습니다")


def customer_tail(customer_id) -> str:
    """로그·오류에 쓰는 고객 번호 표기 — 끝 4자리만."""
    s = str(customer_id)
    return "…" + s[-4:] if len(s) > 4 else "…" + s


@dataclass(frozen=True)
class ManagerCredentials:
    customer_id: int
    api_key: Secret
    secret_key: Secret

    def __repr__(self) -> str:
        return f"ManagerCredentials(customer={customer_tail(self.customer_id)}, api_key={_MASK}, secret_key={_MASK})"

    __str__ = __repr__


def load_manager_credentials(env: Optional[Mapping[str, str]] = None) -> ManagerCredentials:
    """환경변수에서 대행사 키 3종을 읽는다. 하나라도 없거나 고객 번호가 숫자가 아니면 ``CredentialsMissing``."""
    src = os.environ if env is None else env
    missing = [n for n in (ENV_CUSTOMER_ID, ENV_API_KEY, ENV_SECRET_KEY) if not (src.get(n) or "").strip()]
    if missing:
        raise CredentialsMissing("대행사 키가 설정되지 않았습니다: " + ", ".join(missing))
    cid = src[ENV_CUSTOMER_ID].strip()
    if not _DIGITS.fullmatch(cid) or int(cid) <= 0:
        raise CredentialsMissing(f"{ENV_CUSTOMER_ID} 는 숫자여야 합니다")
    for name in (ENV_API_KEY, ENV_SECRET_KEY):
        if not _KEY_CHARS.fullmatch(src[name].strip()):
            # 줄바꿈 등이 섞이면 보낼 때 오류 문구에 키가 통째로 실린다 — 읽을 때 막는다(값은 문구에 넣지 않는다)
            raise CredentialsMissing(f"{name} 에 쓸 수 없는 글자가 있습니다(빈칸·줄바꿈·한글 등)")
    return ManagerCredentials(
        customer_id=int(cid),
        api_key=Secret(src[ENV_API_KEY].strip()),
        secret_key=Secret(src[ENV_SECRET_KEY].strip()),
    )
