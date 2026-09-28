"""가짜 네이버 — 받은 방식·호스트·경로·쿼리·``X-Customer``·서명 검사 결과를 모두 기록한다.

실제 네트워크를 쓰지 않는다(읽기 관문의 보내는 부분 대신 끼운다). 예시 번호·이름·표지 값은 모두 지어낸 것이다.
표지 값(``MARK_*``)은 개인정보·비밀값 자리에 넣어, 반환값·로그·오류 어디에도 나오지 않는지 시험이 찾는다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from naver_engine import handles as H

MARK_API_KEY = "MARKAPIKEY-0f1e2d3c"
MARK_SECRET = "MARKSECRET-9a8b7c6d"
MARK_OWNER = "MARKOWNERNAVERID"       # 하위 계정의 ownerNaverId
MARK_MGR_NAVERID = "MARKMGRNAVERID"   # 관리계정의 naverId
MARK_TRACK = "MARKTRACKINGURL"        # 캠페인 추적 주소
MARK_BIZINFO = "MARKBUSINESSINFO"     # 비즈채널 사업자 정보
MARK_NEWFIELD = "MARKNEWPERSONAL"     # 네이버가 새로 더한(모르는) 칸

AGENCY_ID = 7654321


@dataclass
class Call:
    method: str
    scheme: str
    host: str
    path: str
    query: Dict[str, List[str]]
    customer: Optional[str]
    api_key_ok: bool
    sig_ok: bool
    ts: str
    has_body: bool


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now
        self._mono = 1000.0
        self.sleeps: List[float] = []
        self._ms = int(now.timestamp() * 1000)

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def epoch_ms(self) -> int:
        self._ms += 1  # 요청마다 다른 시각(다시 보낼 때 서명을 새로 하는지 보려고)
        return self._ms

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._mono += seconds
        self._now = self._now + timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._mono += seconds
        self._now = self._now + timedelta(seconds=seconds)


Reply = Tuple[int, object]  # (상태, JSON 으로 보낼 값 · bytes 면 그대로)


class FakeNaver:
    def __init__(self, api_key: str = MARK_API_KEY, secret: str = MARK_SECRET) -> None:
        self.api_key, self.secret = api_key, secret
        self.calls: List[Call] = []
        self.routes: List[Tuple[re.Pattern, Callable[[Call], Reply]]] = []
        self.scripts: Dict[str, List[object]] = {}  # 경로 → 앞에서부터 꺼내 쓰는 응답(예외도 넣을 수 있음)
        self.tick = None  # 매 요청 뒤 부르는 함수(시각 흘려보내기 등)

    def route(self, pattern: str, fn: Callable[[Call], Reply]) -> None:
        self.routes.append((re.compile(pattern), fn))

    def script(self, path: str, *replies) -> None:
        self.scripts.setdefault(path, []).extend(replies)

    def send(self, req, timeout) -> Tuple[int, bytes]:
        u = urllib.parse.urlsplit(req.full_url)
        hdr = {k.lower(): v for k, v in req.header_items()}
        ts = hdr.get("x-timestamp", "")
        expect = base64.b64encode(hmac.new(self.secret.encode(), f"{ts}.{req.get_method()}.{u.path}".encode(),
                                           hashlib.sha256).digest()).decode()
        call = Call(req.get_method(), u.scheme, u.hostname or "", u.path, urllib.parse.parse_qs(u.query),
                    hdr.get("x-customer"), hdr.get("x-api-key") == self.api_key,
                    hdr.get("x-signature") == expect, ts, req.data is not None)
        self.calls.append(call)
        if self.tick:
            self.tick(call)
        queue = self.scripts.get(u.path)
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return self._encode(item)
        for pat, fn in self.routes:
            if pat.fullmatch(u.path):
                return self._encode(fn(call))
        return 404, b'{"code":404,"title":"not found"}'

    @staticmethod
    def _encode(reply: Reply) -> Tuple[int, bytes]:
        status, body = reply
        if isinstance(body, bytes):
            return status, body
        return status, json.dumps(body).encode("utf-8")


# ── 예시 대행사 ──────────────────────────────────────────────────────
def page_of(rows: list, call: Call, total: Optional[int] = None, size_cap: Optional[int] = None) -> Reply:
    page = int(call.query.get("page", ["0"])[0])
    size = int(call.query.get("size", ["1000"])[0])
    if size_cap:
        size = min(size, size_cap)
    chunk = rows[page * size:(page + 1) * size]
    n = len(rows) if total is None else total
    pages = (n + size - 1) // size if size else 0
    return 200, {"content": chunk, "totalElements": n, "totalPages": pages, "number": page,
                 "last": page + 1 >= pages, "size": size, "numberOfElements": len(chunk)}


def make_children(start: int, n: int, role: str = "MASTER") -> list:
    return [{"customerId": start + i, "adAccountNo": 900000 + start + i, "adAccountName": f"예시계정{start + i}",
             "accountRole": role, "ownerNaverId": MARK_OWNER, "newPersonalField": MARK_NEWFIELD} for i in range(n)]


class Agency:
    """관리계정 3개 — 하위 계정 수는 작게 줄였지만 쪽 넘김이 생기게 첫 곳은 1,000 을 넘긴다."""

    def __init__(self, naver: FakeNaver, sizes=(2345, 90, 339)) -> None:
        self.naver = naver
        self.managers = []
        self.children: Dict[int, list] = {}
        start = 3000000
        for i, n in enumerate(sizes, start=1):
            no = 100 + i
            self.managers.append({"managerAccountNo": no, "naverId": MARK_MGR_NAVERID, "roleName": "ADMIN",
                                  "managerAccount": {"no": no, "name": f"관리계정{i}", "childAdAccountCount": n,
                                                     "deleted": False, "disabled": False, "country": "KR"}})
            self.children[no] = make_children(start, n)
            start += 5000
        naver.route(r"/manager-accounts", lambda c: page_of(self.managers, c))
        naver.route(r"/manager-accounts/(\d+)/child-ad-accounts", self._kids)

    def _kids(self, call: Call) -> Reply:
        no = int(call.path.split("/")[2])
        if no not in self.children:
            return 404, {"code": 404}
        return page_of(self.children[no], call)


def campaign(cid: int, n: int, customer: Optional[int] = None) -> dict:
    return {"nccCampaignId": f"cmp-{cid}-{n}", "customerId": cid if customer is None else customer,
            "name": f"캠페인{n}", "campaignTp": "SHOPPING", "status": "ELIGIBLE", "userLock": False,
            "dailyBudget": 50000, "useDailyBudget": True, "trackingUrl": MARK_TRACK,
            "trackingUrlCustomParams": MARK_TRACK, "newPersonalField": MARK_NEWFIELD}


def cycle_str(dt: datetime) -> str:
    return dt.astimezone(H.KST).strftime("%Y%m%d%H%M")
