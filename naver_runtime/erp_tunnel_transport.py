"""고정 ERP 요청을 외부 TCP 없이 전용 SSH 전달 Unix socket으로 보낸다.

이 모듈은 SSH 연결·키·서버 설정을 만들지 않는다. 호출자가 검증한 별도 터널이
필요하며, 논리 HTTPS URL도 여기서는 SSH로 보호된 HTTP이지 TLS 연결이 아니다.
"""
from __future__ import annotations

import base64
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import time
import urllib.parse

from naver_engine import erp_profile as EP
from naver_engine import erp_read as E
from naver_engine.naver_read import MAX_BODY as _URLLIB_MAX_BODY

_READ_PATHS = frozenset((E.PATH_CONTRACTS, E.PATH_ORG_SNAPSHOT, E.PATH_NAVER_IDS, E.PATH_ACCOUNT_CATALOG))
_STAGES = frozenset(s for spellings in E.STAGE_SPELLINGS.values() for s in spellings)


class ErpTunnelError(OSError):
    """경로·키·요청·응답·하위 예외 원문을 포함하지 않는 실패."""

    def __init__(self):
        super().__init__("erp-tunnel-unavailable")


def _json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ErpTunnelError()
    return result


def _request(request):
    url = urllib.parse.urlsplit(request.full_url)
    method = request.get_method()
    allowed = ((method == "GET" and url.scheme == E.ERP_SCHEME and url.path in _READ_PATHS)
               or (method == "POST" and url.scheme == EP.ERP_SCHEME and url.path == EP.PATH_EXCHANGE))
    target = url.path + ("?" + url.query if url.query else "")
    if not allowed or url.netloc != E.ERP_HOST or url.fragment \
            or request.full_url != url.scheme + "://" + E.ERP_HOST + target \
            or len(request.full_url) > 1024 or not re.fullmatch(r"[\x21-\x7e]+", request.full_url) \
            or request.host != E.ERP_HOST or request.type != url.scheme:
        raise ErpTunnelError()
    if url.path == E.PATH_CONTRACTS:
        pairs = urllib.parse.parse_qsl(url.query, strict_parsing=True, max_num_fields=2)
        params = dict(pairs)
        if len(pairs) != 2 or set(params) != {"stage", "has_contract"} \
                or params["stage"] not in _STAGES or params["has_contract"] != "true" \
                or urllib.parse.urlencode(pairs) != url.query:
            raise ErpTunnelError()
    elif url.query:
        raise ErpTunnelError()
    headers = {}
    for name, value in list(request.headers.items()) + list(request.unredirected_hdrs.items()):
        name = name.lower()
        if name in headers or not isinstance(value, str) or not re.fullmatch(r"[\x21-\x7e]{1,256}", value):
            raise ErpTunnelError()
        headers[name] = value
    expected = ({"accept", "x-api-key"} if method == "GET"
                else {"accept", "content-type", "x-sso-client-key"})
    if set(headers) != expected or headers["accept"] != "application/json":
        raise ErpTunnelError()
    if method == "GET":
        if request.data is not None or not E.KEY_MIN_LENGTH <= len(headers["x-api-key"]) <= E.KEY_MAX_LENGTH:
            raise ErpTunnelError()
        body = b""
    else:
        body = request.data
        if headers["content-type"] != "application/json" \
                or not re.fullmatch(r"[0-9a-fA-F]{64}", headers["x-sso-client-key"]) \
                or not isinstance(body, bytes) or len(body) > 1024:
            raise ErpTunnelError()
        values = json.loads(body, object_pairs_hook=_json_object)
        if not isinstance(values, dict):
            raise ErpTunnelError()
        if set(values) != {"destination", "code", "codeVerifier"} or values["destination"] != "NAVER_CONTROL":
            raise ErpTunnelError()
        for field in ("code", "codeVerifier"):
            value = values[field]
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value) \
                    or base64.urlsafe_b64encode(base64.urlsafe_b64decode(value + "=")).decode().rstrip("=") != value:
                raise ErpTunnelError()
    headers.update({"Host": E.ERP_HOST, "Connection": "close", "User-Agent": "Python-urllib/3 NaverControl"})
    if body:
        headers["Content-Length"] = str(len(body))
    return method, target, headers, body


def _read_response(response, limit):
    response.begin()
    if 300 <= response.status < 400:
        raise ErpTunnelError()
    if response.status != 200:
        # 거절 응답의 키/행 자료/프록시 오류 본문을 호출자에게 전달하지 않는다.
        return response.status, b""
    lengths = response.headers.get_all("Content-Length", [])
    transfers = response.headers.get_all("Transfer-Encoding", [])
    encodings = response.headers.get_all("Content-Encoding", [])
    if len(lengths) > 1 or len(transfers) > 1 or (lengths and transfers) \
            or (transfers and transfers != ["chunked"]) \
            or (encodings and encodings != ["identity"]):
        raise ErpTunnelError()
    expected = None
    if lengths:
        if not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            raise ErpTunnelError()
        expected = int(lengths[0])
        if expected > limit:
            raise ErpTunnelError()
    body = response.read(limit + 1)
    if len(body) > limit or (expected is not None and len(body) != expected):
        raise ErpTunnelError()
    return response.status, body


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise ErpTunnelError()
    return left


class _DeadlineReader(io.RawIOBase):
    """HTTP 상태줄/헤더/본문의 모든 recv에 같은 전체 마감을 적용한다."""

    def __init__(self, conn, deadline):
        super().__init__()
        self.conn, self.deadline = conn, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.conn.settimeout(_remaining(self.deadline))
        return self.conn.recv_into(buffer)


class _ResponseSocket:
    def __init__(self, conn, deadline):
        self.reader = _DeadlineReader(conn, deadline)

    def makefile(self, mode):
        return io.BufferedReader(self.reader)


def _socket_identity(path):
    """private 부모/소켓만 허용. 같은 신뢰 UID의 동시 교체도 연결 뒤 다시 검사한다."""
    parent = Path(path).parent
    directory = parent.lstat()
    target = os.lstat(path)
    trusted = {0, os.geteuid()}
    if parent.resolve(strict=True) != parent or not stat.S_ISDIR(directory.st_mode) \
            or directory.st_uid not in trusted or directory.st_mode & 0o022 \
            or not stat.S_ISSOCK(target.st_mode) or target.st_uid not in trusted \
            or target.st_mode & 0o007:
        raise ErpTunnelError()
    # /tmp처럼 root 소유 sticky 부모는 허용하되, 다른 사용자가 private 디렉터리
    # 자체를 바꿔치기할 수 있는 상위 디렉터리는 허용하지 않는다.
    for ancestor in parent.parents:
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in trusted \
                or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
            raise ErpTunnelError()
    return target.st_dev, target.st_ino, target.st_uid, target.st_gid, target.st_mode


class ErpTunnelTransport:
    """Reader 공통 send(request, timeout) → (status, bytes).

    socket_path는 정규 절대 경로(100바이트 이내), 부모는 root/현재 UID 소유이며
    그룹·기타 쓰기 금지, socket은 root/현재 UID 소유이며 기타 접근 금지여야 한다.
    매 호출 새 AF_UNIX 연결 한 번만 사용한다. DNS/TCP/프록시/넘겨주기/재시도 없음.
    timeout은 양수이고 조회 30초/SSO 8초 이내이며 전체 송수신에 적용한다.
    응답 상한은 기존 실제 전송과 같은 조회 16MiB, SSO 256KiB이다.
    200 외 본문은 버리고, 3xx/잘린 응답/구성·전송 실패는 ErpTunnelError로 닫는다.
    SSH 상대 신원과 원격 4경로 ingress 검증은 이 모듈 밖 별도 배포 게이트다.
    """

    def __init__(self, socket_path: str):
        if not isinstance(socket_path, str) or not socket_path.startswith("/") \
                or "\x00" in socket_path or len(os.fsencode(socket_path)) > 100 \
                or any(part in ("", ".", "..") for part in socket_path.split("/")[1:]):
            raise ErpTunnelError()
        self._path = socket_path

    def send(self, request, timeout):
        try:
            method, target, headers, body = _request(request)
            maximum = EP.TIMEOUT if method == "POST" else E.TIMEOUT
            if type(timeout) not in (int, float) or not 0 < timeout <= maximum or not math.isfinite(timeout):
                raise ErpTunnelError()
            deadline = time.monotonic() + timeout
            identity = _socket_identity(self._path)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(_remaining(deadline))
                conn.connect(self._path)
                if _socket_identity(self._path) != identity:
                    raise ErpTunnelError()
                wire = (method + " " + target + " HTTP/1.1\r\n"
                        + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n").encode("ascii")
                conn.settimeout(_remaining(deadline))
                conn.sendall(wire + body)
                with http.client.HTTPResponse(_ResponseSocket(conn, deadline)) as response:
                    limit = EP.MAX_BODY if method == "POST" else min(E.MAX_BODY, _URLLIB_MAX_BODY)
                    result = _read_response(response, limit)
                    _remaining(deadline)
                    return result
        except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError, RuntimeError):
            raise ErpTunnelError() from None
