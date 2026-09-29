"""/naver/ 화면 입구 · /api/naver-auto/* 중계(S12) — 얇은 연결만. 규칙은 ``app/naver_relay.py`` 한 곳.

- 스위치(``NAVER_AUTO_WEB=on``)가 꺼져 있으면 두 길 모두 **없는 주소와 똑같은 404** — 정적 파일 마운트보다 먼저 받는다(M6).
- 중계 경로는 동기 ``def``(스레드풀) — 엔진이 느려도 ③ 다른 요청(``/api/health`` 등)이 기다리지 않는다(M7).
  본문 읽기만 비동기 의존성에서 64KB 상한으로 한다(엔진에 보내기 전에 끊는다).
- ③ 로그인(JWT)을 쓰지 않는다 — 엔진이 자기 토큰으로 사람을 가린다.
"""
from __future__ import annotations

import pathlib
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .. import naver_relay as R

router = APIRouter(tags=["naver-auto"], include_in_schema=False)

PAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "static" / "naver"
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _off() -> HTTPException:
    return HTTPException(status_code=404, detail="Not Found")     # 없는 주소의 답과 같다


async def _capped_body(request: Request) -> Union[None, bytes, int]:
    """POST 본문만 · 64KB 넘으면 더 읽지 않고 413. 꺼져 있으면 읽지 않고 404."""
    if not R.enabled():
        raise _off()
    if request.method != "POST":
        return None
    cl = request.headers.get("content-length")
    if cl is not None:
        if not cl.isdigit():
            return 400
        if int(cl) > R.BODY_MAX:
            return 413
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > R.BODY_MAX:
            return 413
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
        raise _off() from None


def _page(request: Request, rest: str) -> Response:
    if not R.enabled():
        raise _off()
    if request.method not in ("GET", "HEAD"):
        raise HTTPException(status_code=405, detail="Method Not Allowed")
    p: Optional[pathlib.Path] = R.page_file(PAGE_ROOT, rest)
    if p is None:
        raise _off()
    return FileResponse(str(p), media_type=R.page_type(p), headers=dict(R.PAGE_HEADERS))


@router.api_route("/naver", methods=_METHODS)
def naver_page_bare(request: Request) -> Response:
    return _page(request, "")


@router.api_route("/naver/", methods=_METHODS)
def naver_page_root(request: Request) -> Response:
    return _page(request, "")


@router.api_route("/naver/{rest:path}", methods=_METHODS)
def naver_page_file(rest: str, request: Request) -> Response:
    return _page(request, rest)
