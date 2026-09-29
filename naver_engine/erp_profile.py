"""① 내 정보 관문 — 관제 화면 로그인 때 ① ``my-profile`` 을 **한 번** 부르는 문 하나(설계 v1.4 §9 · S11).

엔진이 ① 에 하는 호출은 관문 셋(읽기 ``erp_read`` · 알림 ``erp_alert`` · 이 문)만 지난다. 이 문은:

- **GET 만** · 주소는 ``/api/employee-management/my-profile`` 하나 · 호스트·주소 글자는 읽기 관문의 것을 가져다 쓴다
  (스스로 적지 않는다 — 구문 시험이 고정).
- 넘겨주기를 따라가지 않고 환경 프록시를 무시한다(네이버 관문과 같은 전송 ``UrllibTransport``).
- ① 로그인 토큰(sso)은 ``Secret`` 로만 들고, 꺼내는 곳은 ``_gate`` 한 곳이다. **저장하지 않고 · 기록·예외 문구에 싣지 않는다.**
  엔진 전용 키는 쓰지 않는다(이 경로는 직원 본인의 토큰으로만 열린다).
- **남길 칸만** — 직원 번호(``result.idx`` · 대표 = 0) · 팀장 표시(``isManager``) · 소속 팀 번호 사슬(``teamList`` 의
  ``idx``·``parentIdx``). 로그인 아이디(``id``) · 이름 · 전화 · 주민번호 · 주소 · 계좌 · 권한 칸은 읽자마자 버린다
  (응답 전체를 어디에도 두지 않는다). ⚠️ ③ 기존 로그인은 ``result.id``(로그인 아이디 글자)를 쓴다 — 이 문은 ``idx`` 만 쓴다.
- **200 이 아니면 성공이 아니다** · 401·403 은 「토큰 거절」 · 그 밖은 「① 응답 없음」 · 본문 크기 상한 · JSON 이 아니면 실패.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

from .credentials import Secret
from .erp_read import BASE_URL, ERP_HOST, ERP_SCHEME
from .naver_read import UrllibTransport

PATH_MY_PROFILE = "/api/employee-management/my-profile"
_ALLOWED_METHODS = frozenset({"GET"})
TIMEOUT = 8                      # ③ 기존 로그인과 같다(auth.py)
MAX_BODY = 256 * 1024
SSO_MIN_LENGTH, SSO_MAX_LENGTH = 16, 4096
_SSO_CHARS = re.compile(r"[A-Za-z0-9._~+/=-]+")   # 토큰 모양(JWT · base64url) — 빈칸·줄바꿈·따옴표 없음
TEAM_LIST_MAX = 64

KIND_REJECTED = "sso-rejected"   # ① 이 토큰을 거절(401·403) — 전산에서 다시 들어와야 한다
KIND_UNAVAILABLE = "erp-unavailable"
KIND_BAD_SHAPE = "erp-bad-shape"


class ProfileError(RuntimeError):
    """① 내 정보 읽기 실패 — ``kind`` 만 싣는다(토큰·응답 내용 없음)."""

    def __init__(self, kind: str, status: Optional[int] = None) -> None:
        self.kind, self.status = kind, status
        super().__init__(f"① 내 정보 읽기 실패 [{kind}] 상태 {status}")


class ProfileForbidden(RuntimeError):
    """GET 이 아닌 요청 · 허용하지 않은 경로·호스트."""


def load_sso(raw) -> Secret:
    """화면이 넘긴 ① 토큰 → ``Secret``. 모양이 틀리면 ``ProfileError(sso-rejected)``(값은 문구에 없다)."""
    if not isinstance(raw, str):
        raise ProfileError(KIND_REJECTED)
    tok = raw.strip()
    if not SSO_MIN_LENGTH <= len(tok) <= SSO_MAX_LENGTH or not _SSO_CHARS.fullmatch(tok):
        raise ProfileError(KIND_REJECTED)
    return Secret(tok)


@dataclass(frozen=True)
class Profile:
    """남긴 칸만 — 번호 · 팀장이라고 하는지 · 가장 깊은 팀(모르면 ``team_known`` 거짓)."""
    idx: int
    says_manager: Optional[bool]     # ① isManager — 참거짓이 아니면 None(모름)
    team_idx: Optional[int]
    team_known: bool

    def __repr__(self) -> str:   # 번호도 로그에 흘리지 않는다
        return "Profile(****)"


def _int(v, lo: int) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, int) or v < lo or v >= 2 ** 63:
        return None
    return v


def _leaf_team(team_list) -> Tuple[Optional[int], bool]:
    """① ``teamList`` = 본인 팀에서 위로 가는 조상 사슬. 부모로 가리켜지지 않는 팀이 딱 하나면 그것이 본인 팀.
    빈 목록 = 팀 없음(아는 것) · 모양이 틀리거나 끝이 여럿이면 모름."""
    if team_list is None:
        return None, False
    if not isinstance(team_list, list) or len(team_list) > TEAM_LIST_MAX:
        return None, False
    if not team_list:
        return None, True
    ids, parents = set(), set()
    for t in team_list:
        if not isinstance(t, dict):
            return None, False
        i = _int(t.get("idx"), 0)
        par = t.get("parentIdx")
        if i is None or (par is not None and _int(par, 0) is None) or i in ids:
            return None, False
        ids.add(i)
        if par is not None:
            parents.add(par)
    leaves = ids - parents
    if len(leaves) != 1:
        return None, False
    return next(iter(leaves)), True


class ErpProfileReader:
    def __init__(self, transport=None) -> None:
        self._transport = transport or UrllibTransport()
        self.calls = 0

    def __repr__(self) -> str:
        return f"ErpProfileReader(calls={self.calls})"

    # ── 관문 ──────────────────────────────────────────────────────
    def _gate(self, method: str, path: str, sso: Secret) -> Tuple[int, bytes]:
        if method not in _ALLOWED_METHODS:
            raise ProfileForbidden(f"GET 이 아닌 요청은 만들지 않습니다: {method}")
        if path != PATH_MY_PROFILE:
            raise ProfileForbidden("허용하지 않은 경로")
        if not isinstance(sso, Secret):
            raise ProfileForbidden("토큰은 Secret 이어야 합니다")
        self.calls += 1
        headers = {"Authorization": "Bearer " + sso.reveal(), "Accept": "application/json"}
        req = urllib.request.Request(BASE_URL + path, headers=headers, method=method)
        if req.get_method() != "GET" or req.data is not None:
            raise ProfileForbidden("GET 이 아닌 요청은 보내지 않습니다")
        if req.host != ERP_HOST or req.type != ERP_SCHEME:
            raise ProfileForbidden("허용하지 않은 호스트")
        del headers
        try:
            return self._transport.send(req, TIMEOUT)
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise ProfileError(KIND_UNAVAILABLE) from None
        except Exception:  # 뜻밖의 오류 — 문구에 토큰이 섞일 수 있어 종류만 남긴다
            raise ProfileError(KIND_UNAVAILABLE) from None

    def _get(self, sso: Secret) -> dict:
        status, body = self._gate("GET", PATH_MY_PROFILE, sso)
        if status in (401, 403):
            raise ProfileError(KIND_REJECTED, status)
        if status != 200:
            raise ProfileError(KIND_UNAVAILABLE, status)
        if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_BODY:
            raise ProfileError(KIND_BAD_SHAPE, status)
        try:
            j = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ProfileError(KIND_BAD_SHAPE, status) from None
        if not isinstance(j, dict) or not isinstance(j.get("result"), dict) \
                or ("status" in j and j.get("status") != 200):
            raise ProfileError(KIND_BAD_SHAPE, status)
        return j["result"]

    def read_profile(self, sso: Secret) -> Profile:
        """① 내 정보 → 남길 칸만. 번호가 0 이상의 정수가 아니면 실패(대표 = 0 은 사람이다)."""
        res = self._get(sso)
        idx = _int(res.get("idx"), 0)
        if idx is None:
            raise ProfileError(KIND_BAD_SHAPE, 200)
        mgr = res.get("isManager")
        team, known = _leaf_team(res.get("teamList"))
        return Profile(idx, mgr if type(mgr) is bool else None, team, known)
