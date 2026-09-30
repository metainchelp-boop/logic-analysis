"""S16 전산 일회용 로그인 교환 관문.

고정 HTTPS POST /api/sso/exchange 한 곳만 사용한다. 목적지는 NAVER_CONTROL이며
별도 서버 키와 브라우저 검증자를 함께 보낸다. 기존 ERP JWT/my-profile 경로는 사용하지 않는다.
코드·검증자·서버 키는 Secret으로 감싸고 요청을 만드는 _gate에서만 꺼낸다.
넘겨주기·환경 프록시·자동 재시도 없음. 응답은 번호·팀장·팀 번호만 남긴다.
대표 idx0을 보존하며 만료/재사용/다른 목적지/PKCE 거절은 전산의401을 그대로 거절 처리한다.
"""
from __future__ import annotations

import http.client
import json
import re
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

from .credentials import Secret
from .naver_read import UrllibTransport

ERP_HOST, ERP_SCHEME = 'api.metainc.co.kr', 'https'
BASE_URL = ERP_SCHEME + '://' + ERP_HOST
PATH_EXCHANGE = '/api/sso/exchange'
_ALLOWED_METHODS = frozenset({"POST"})
TIMEOUT = 8                      # ③ 기존 로그인과 같다(auth.py)
MAX_BODY = 256 * 1024
_CODE_CHARS = re.compile(r"[A-Za-z0-9_-]{43}")
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


def load_code(raw) -> Secret:
    """32바이트 base64url 코드/검증자만. 기존 JWT·공백·Bearer 접두사는 받지 않는다."""
    if not isinstance(raw, str) or not _CODE_CHARS.fullmatch(raw):
        raise ProfileError(KIND_REJECTED)
    return Secret(raw)


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
    def __init__(self, transport=None, env=None) -> None:
        self._transport = transport or UrllibTransport()
        value = (os.environ if env is None else env).get('SSO_NAVER_CONTROL_CLIENT_KEY', '')
        self._key = Secret(value) if isinstance(value, str) and re.fullmatch(r'[a-fA-F0-9]{64}', value) else None
        self.calls = 0

    def __repr__(self) -> str:
        return f"ErpProfileReader(calls={self.calls})"

    def require_configured(self) -> None:
        if self._key is None:
            raise ProfileError(KIND_UNAVAILABLE)

    # ── 관문 ──────────────────────────────────────────────────────
    def _gate(self, method: str, path: str, code: Secret, verifier: Secret) -> Tuple[int, bytes]:
        if method not in _ALLOWED_METHODS:
            raise ProfileForbidden("허용하지 않은 방식")
        if path != PATH_EXCHANGE:
            raise ProfileForbidden("허용하지 않은 경로")
        if not isinstance(code, Secret) or not isinstance(verifier, Secret):
            raise ProfileForbidden("코드와 검증자는 Secret 이어야 합니다")
        self.require_configured()
        self.calls += 1
        headers = {"X-Sso-Client-Key": self._key.reveal(), "Accept": "application/json", 'Content-Type':'application/json'}
        body = json.dumps({'destination':'NAVER_CONTROL', 'code':code.reveal(), 'codeVerifier':verifier.reveal()}).encode('ascii')
        req = urllib.request.Request(BASE_URL + path, headers=headers, method=method, data=body)
        if req.get_method() != "POST":
            raise ProfileForbidden("허용하지 않은 방식")
        if req.host != ERP_HOST or req.type != ERP_SCHEME:
            raise ProfileForbidden("허용하지 않은 호스트")
        del headers
        try:
            return self._transport.send(req, TIMEOUT)
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise ProfileError(KIND_UNAVAILABLE) from None
        except Exception:  # 뜻밖의 오류 — 문구에 토큰이 섞일 수 있어 종류만 남긴다
            raise ProfileError(KIND_UNAVAILABLE) from None

    def _get(self, code: Secret, verifier: Secret) -> dict:
        status, body = self._gate("POST", PATH_EXCHANGE, code, verifier)
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
                or j.get("status") != 200:
            raise ProfileError(KIND_BAD_SHAPE, status)
        return j["result"]

    def read_profile(self, code: Secret, verifier: Secret) -> Profile:
        """① 내 정보 → 남길 칸만. 번호가 0 이상의 정수가 아니면 실패(대표 = 0 은 사람이다)."""
        res = self._get(code, verifier)
        idx = _int(res.get("idx"), 0)
        if idx is None:
            raise ProfileError(KIND_BAD_SHAPE, 200)
        mgr = res.get("isManager")
        team, known = _leaf_team(res.get("teamList"))
        return Profile(idx, mgr if type(mgr) is bool else None, team, known)
