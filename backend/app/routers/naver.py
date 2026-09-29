"""/naver/ 화면 입구 · /api/naver-auto/* 중계(S12) — 얇은 연결만. 규칙은 ``app/naver_relay.py`` 한 곳.

- 스위치(``NAVER_AUTO_WEB=on``)가 꺼져 있으면 두 길 모두 **라우트가 아예 맞지 않는다**(``_SwitchedRoute``) — 요청이
  정적 마운트로 그대로 흘러가 S12 이전과 바이트까지 같은 답(GET·HEAD 404 · 그 밖 405 · 점 조각 주소의 옛 답까지).
  켜져 있을 때만 정적 파일 마운트보다 먼저 받는다(M6). 핸들러 안의 꺼짐 확인은 요청 도중 스위치가 바뀌는 틈을 막는 겹.
- 화면 파일은 **정적 마운트 폴더(``static/``) 밖** ``backend/naver_page/`` 에 둔다 — 마운트가 어떤 주소 철자
  (``//naver/`` · ``/./naver/`` · ``/x/../naver/``)로도 닿지 못해 이 라우터가 유일한 입구다(S12 검토 static-mount-bypass).
- ``/naver``(끝 빗금 없음)는 받지 않는다 — 없는 주소와 같다. ① 링크는 ``/naver/`` 로 온다.
- 중계 경로는 동기 ``def``(스레드풀) — 엔진이 느려도 ③ 다른 요청(``/api/health`` 등)이 기다리지 않는다(M7).
  본문 읽기만 비동기 의존성에서 64KB 상한으로 한다(엔진에 보내기 전에 끊는다).
- ③ 로그인(JWT)을 쓰지 않는다 — 엔진이 자기 토큰으로 사람을 가린다.
- 켜져 있을 때 화면 쪽 404·405 에도 ``no-referrer`` · ``no-store`` — 주소창의 ① sso 가 favicon 요청의 Referer 로
  nginx 기록에 남거나 디스크 캐시에 남지 않게(S12 2차 검토). 꺼져 있을 때의 같은 머리는 S14 nginx 몫.
"""
from __future__ import annotations

import pathlib
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.routing import APIRoute
from starlette.requests import ClientDisconnect
from starlette.routing import Match

from .. import naver_relay as R


class _SwitchedRoute(APIRoute):
    """스위치가 꺼져 있으면 맞지 않는 라우트 — 요청이 정적 마운트(없는 주소의 답)로 그대로 간다."""

    def matches(self, scope):
        if not R.enabled():
            return Match.NONE, {}
        return super().matches(scope)


router = APIRouter(tags=["naver-auto"], include_in_schema=False, route_class=_SwitchedRoute)

PAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "naver_page"
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_PAGE_MISS_HEADERS = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


def _off(method: str) -> HTTPException:
    """꺼져 있을 때 — 없는 주소의 답과 같게(정적 마운트는 GET·HEAD 에 404 · 그 밖 방식에 405)."""
    if method in ("GET", "HEAD"):
        return HTTPException(status_code=404, detail="Not Found")
    return HTTPException(status_code=405, detail="Method Not Allowed")


async def _capped_body(request: Request) -> Union[None, bytes, int]:
    """POST 본문만 · 64KB 넘으면 더 읽지 않고 413. 꺼져 있으면 읽지 않고 없는 주소와 같은 답."""
    if not R.enabled():
        raise _off(request.method)
    if request.method != "POST":
        return None
    cl = request.headers.get("content-length")
    if cl is not None:
        if not cl.isdigit():
            return 400
        if int(cl) > R.BODY_MAX:
            return 413
    buf = bytearray()
    try:
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > R.BODY_MAX:
                return 413
    except ClientDisconnect:                  # 보내다 끊은 브라우저 — 답은 나가지 않는다 · 스택 기록 없이
        return 400
    return bytes(buf)


def _answer(out: R.Outgoing) -> Response:
    return Response(content=out.body, status_code=out.status, headers=dict(out.headers))


@router.api_route(R.PREFIX + "/{sub:path}", methods=_METHODS)
def naver_relay_route(sub: str, request: Request, body: Union[None, bytes, int] = Depends(_capped_body)) -> Response:
    if isinstance(body, int):
        return _answer(R._err(body, "too-large" if body == 413 else "bad-length"))
    h = request.headers
    inc = R.Incoming(
        method=request.method,
        sub="/" + sub,
        query=request.scope.get("query_string", b"").decode("latin-1"),
        authorization=tuple(h.getlist("authorization")),
        content_type=h.get("content-type"),
        body=body,
        real_ip=h.get("x-real-ip"),
        peer=request.client.host if request.client else None,
        origin=h.get("origin"),
        host=h.get("host"),
        fetch_site=h.get("sec-fetch-site"),
    )
    try:
        return _answer(R.relay(inc))
    except R.RelayOff:
        raise _off(request.method) from None


def _page(request: Request, rest: str) -> Response:
    if not R.enabled():
        raise _off(request.method)
    if request.method not in ("GET", "HEAD"):
        raise HTTPException(status_code=405, detail="Method Not Allowed", headers=dict(_PAGE_MISS_HEADERS))
    p: Optional[pathlib.Path] = R.page_file(PAGE_ROOT, rest)
    if p is None:
        raise HTTPException(status_code=404, detail="Not Found", headers=dict(_PAGE_MISS_HEADERS))
    return FileResponse(str(p), media_type=R.page_type(p), headers=dict(R.PAGE_HEADERS))


@router.api_route("/naver/", methods=_METHODS)
def naver_page_root(request: Request) -> Response:
    return _page(request, "")


@router.api_route("/naver/{rest:path}", methods=_METHODS)
def naver_page_file(rest: str, request: Request) -> Response:
    return _page(request, rest)
