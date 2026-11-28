# -*- coding: utf-8 -*-
"""요청을 보낸 사람의 실제 접속 주소 (2026-11-28 · 섹션 소식판 ①→② 9/24 요청).

왜 만들었나
  로직분석은 서버의 nginx 뒤 도커 컨테이너에서 돈다. 앱이 보는 상대 주소(request.client.host)는
  언제나 nginx 쪽 도커 게이트웨이 하나라, 로그인 기록이 10/1 이후 4,550건 전부 같은 사설 주소였다
  (11/28 읽기 전용 실측). 「누가 어디서 들어왔나」를 기록으로 가릴 수 없었고, 공개 보고서 열람
  분당 제한도 모든 열람자가 한 주소로 묶여 있었다.

어떻게
  nginx 가 `/api/` 로 넘길 때 `X-Real-IP $remote_addr`(손님이 보낸 같은 이름 헤더를 덮어씀)와
  `X-Forwarded-For $proxy_add_x_forwarded_for` 를 붙인다(11/28 nginx -T 실측).
  ⚠️ 상대 주소가 사설·루프백(= 같은 서버의 nginx)일 때만 그 헤더를 믿는다. 바깥에서 곧장 들어온
     요청이 헤더를 지어 보내 주소를 속이지 못하게 한다(컨테이너 포트는 서버 안에만 열려 있다).
  ⚠️ X-Forwarded-For 는 손님이 보낸 값 뒤에 nginx 가 덧붙이므로 **맨 뒤 하나**만 믿는다(맨 앞은 손님이 지어낼 수 있다).
"""
import ipaddress


def _valid(v: str) -> bool:
    try:
        ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


# 같은 서버 nginx 로 보는 상대 주소 — 내부망(도커 게이트웨이는 172.16/12)과 루프백만.
# ⚠️ ipaddress 의 is_private 는 문서용 예시 대역(192.0.2/24 · 198.51.100/24 · 203.0.113/24) 같은 특수 대역도
#    「사설」로 쳐서 쓰지 않는다 — 믿는 범위는 좁을수록 안전하다.
_PROXY_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7"))


def _from_proxy(peer: str) -> bool:
    try:
        a = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):     # ::ffff:172.18.0.1 처럼 IPv6 로 감싼 IPv4 상대
        a = a.ipv4_mapped
    return any(a.version == n.version and a in n for n in _PROXY_NETS)


def client_ip(request, default: str = "") -> str:
    """요청의 실제 접속 주소. 못 읽으면 default."""
    try:
        peer = request.client.host if (request is not None and getattr(request, "client", None)) else ""
    except Exception:
        peer = ""
    peer = peer or ""
    if peer and _from_proxy(peer):
        try:
            headers = request.headers
            real = (headers.get("x-real-ip") or "").strip()
            if not _valid(real):
                real = (headers.get("x-forwarded-for") or "").split(",")[-1].strip()
            if _valid(real):
                return real
        except Exception:
            pass
    return peer or default
