"""① 전산 읽기 관문 — 엔진이 ① 에 하는 모든 호출은 이 문 하나만 지난다(설계 v1.8 S5 · M9 · H3 · L5).

지키는 것:
- **GET 만** · 호스트 ``api.metainc.co.kr`` 글자 그대로 · 경로는 세 개만(계약 단계 · 조직 스냅숏 · 네이버 고객 번호).
  ⚠️ ① 호스트는 HTTP 뿐이다(대표 결정 2026-09-22 「HTTPS 는 안 할 거야」) — 키가 평문으로 가는 위험은 설계 11장 L11.
  ③ 기존 계약 동기화(``backend/app/erp_sync.py``)도 같은 호스트·같은 키를 이미 쓴다.
- 넘겨주기(301·302…)를 따라가지 않고 환경 프록시를 무시한다(네이버 관문과 같은 전송 ``UrllibTransport``).
- 키는 ``Secret`` 로만 들고, 꺼내는 곳은 관문 ``_gate`` 한 곳이다.
- **200 이 아니면 성공이 아니다** · 본문 크기 상한 · JSON 이 아니면 실패 · 문구에 키·업체 이름을 싣지 않는다.
- **단계 동기화는 전부 되거나 전부 안 된 것이다** — 한 번이라도 실패하면 ``ErpIncomplete`` 로 통째로 버린다
  (일부 단계만 받은 목록으로 광고주를 「관리 대상 아님」으로 떨어뜨리지 않게).
- **단계 이름은 띄어쓴 표기 · 붙여 쓴 표기를 모두 부르고 가망 번호로 합친다**(반박 H3 — ① 코드에 두 표기가 섞여 있고
  ① 은 이름을 정확 일치로 찾는다). 한 가망이 두 단계에 나오면(읽는 사이 단계가 바뀜) 「단계 겹침」으로 따로 둔다.
- **남길 칸만** — 가망 번호 · 상호 · 단계 · 계약 종료일(가장 늦은 날). 담당자 이름·금액·상품·주소 같은 칸은 버린다.
- 호출 수 상한 · 순서대로 한 번에 하나(① 은 커넥션 풀 고갈을 여러 번 겪었다 · 단계당 한 번 · 하루 한 번).
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import handles as H
from .credentials import CredentialsMissing, Secret
from .naver_read import SystemClock, UrllibTransport

log = logging.getLogger("naver_engine.erp_read")

ERP_HOST = "api.metainc.co.kr"
ERP_SCHEME = "http"
BASE_URL = ERP_SCHEME + "://" + ERP_HOST
PATH_CONTRACTS = "/api/ad-sync/contracts"
PATH_ORG_SNAPSHOT = "/api/ad-sync/org-snapshot"
PATH_NAVER_IDS = "/api/ad-sync/naver-customer-ids"
_PATHS = frozenset({PATH_CONTRACTS, PATH_ORG_SNAPSHOT, PATH_NAVER_IDS})
_ALLOWED_METHODS = frozenset({"GET"})

ENV_ERP_API_KEY = "ERP_SYNC_API_KEY"     # ③ 계약 동기화와 같은 이름 · 값은 ① AD_SYNC_API_KEY 와 같다
TIMEOUT = 30
MAX_BODY = 30 * 1024 * 1024
MAX_CALLS = 40                            # 한 회차 — 단계 표기 15번 + 스냅숏 + 고객 번호 + 여유
EXPECTED_MANAGED = 940                    # v1.7 실측 관리 단계 광고주 수 — 첫 회차 ±20% 대조(반박 H3)
EXPECTED_TOLERANCE = 0.2

# 빈칸 뺀 열쇠(handles.MONITORED_STAGES) → ① 에 물어볼 표기들. ① 코드·schema.sql 에서 실제로 쓰인 표기를 모두 넣었다
# (2026-09-28 확인: 「진행중」·「진행 중」 · 「사후관리」·「사후 관리」 · 「재계약진행중」·「재계약 진행중」 …).
STAGE_SPELLINGS: Dict[str, Tuple[str, ...]] = {
    "진행중": ("진행중", "진행 중"),
    "전략관리": ("전략 관리", "전략관리"),
    "사후관리": ("사후 관리", "사후관리"),
    "홀딩중": ("홀딩중", "홀딩 중"),
    "재계약진행중": ("재계약 진행중", "재계약진행중", "재계약 진행 중"),
    "환불중": ("환불중", "환불 중"),
    "계약만료": ("계약 만료", "계약만료"),
}
_ALL_SPELLINGS = frozenset(s for v in STAGE_SPELLINGS.values() for s in v)
_WS = re.compile(r"\s+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ErpError(RuntimeError):
    """① 호출 실패. 문구에 키·업체 이름을 싣지 않는다."""

    def __init__(self, kind: str, path: str, status: Optional[int] = None, detail: str = "") -> None:
        self.kind, self.path, self.status, self.detail = kind, path, status, detail
        super().__init__(f"① 읽기 실패 [{kind}] {path} 상태 {status} {detail}".strip())


class ErpIncomplete(ErpError):
    """전부 받지 못함 — 통째로 버린다."""


class ErpWriteForbidden(RuntimeError):
    """GET 이 아닌 요청 · 허용하지 않은 경로·호스트·단계 이름."""


def load_erp_key(env: Optional[Mapping[str, str]] = None) -> Secret:
    """① ad-sync 키를 환경변수에서 읽는다. 없거나 쓸 수 없는 글자가 있으면 ``CredentialsMissing``(문구에 이름만)."""
    src = os.environ if env is None else env
    raw = (src.get(ENV_ERP_API_KEY) or "").strip()
    if not raw:
        raise CredentialsMissing(f"① 키가 설정되지 않았습니다: {ENV_ERP_API_KEY}")
    if not re.fullmatch(r"[\x21-\x7e]{8,512}", raw):
        raise CredentialsMissing(f"{ENV_ERP_API_KEY} 에 쓸 수 없는 글자가 있습니다(빈칸·줄바꿈·한글 등)")
    return Secret(raw)


# ── 결과 모양 ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageRow:
    """관리 단계 가망 한 곳 — 남길 칸만."""
    possibility_id: int
    stage_key: str                                   # 빈칸 뺀 단계(handles.MONITORED_STAGES 의 글자)
    name: Optional[str] = field(default=None, repr=False)
    latest_end_date: Optional[date] = None           # 계약 줄 종료일 중 가장 늦은 날 · 없으면 None
    end_unreadable: bool = False                     # 종료일이 적혀 있는데 못 읽음 → 들어가지 않는다(14일 규칙을 못 지킴)


@dataclass(frozen=True)
class StageSnapshot:
    """7단계 전부를 한 회차에 받은 결과(전부 받았을 때만 만들어진다)."""
    rows: Dict[int, StageRow]
    as_of: datetime                                  # 받은 시각(KST) — 손잡이의 stage_as_of
    per_spelling: Dict[str, int]                     # 표기 → 받은 줄 수
    stage_conflicts: Tuple[int, ...]                 # 두 단계에 나온 가망 — 오늘은 들어가지 않는다

    def __repr__(self) -> str:   # 번호·이름이 로그에 새지 않게 — 개수만
        return f"StageSnapshot(rows={len(self.rows)}, conflicts={len(self.stage_conflicts)})"

    def plausible(self, expected: int = EXPECTED_MANAGED, tolerance: float = EXPECTED_TOLERANCE) -> bool:
        """첫 회차 대조 — 관리 단계 광고주 수가 v1.7 실측과 크게 다르면 표기를 놓쳤을 수 있다(반박 H3)."""
        n = len(self.rows) + len(self.stage_conflicts)
        return abs(n - expected) <= expected * tolerance


@dataclass(frozen=True)
class NaverIdRow:
    possibility_id: int
    vendor: Optional[str]
    customer_id_raw: Optional[str] = field(default=None, repr=False)


def _parse_date(raw) -> Tuple[Optional[date], bool]:
    """(날짜, 못 읽음) — 빈 값은 (None, False) · 틀린 글자는 (None, True)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, False
    if not isinstance(raw, str) or not _DATE.fullmatch(raw.strip()):
        return None, True
    try:
        return date.fromisoformat(raw.strip()), False
    except ValueError:
        return None, True


def _pid(v) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        return None
    return v


class ErpReader:
    def __init__(self, key: Secret, transport=None, clock=None, max_calls: int = MAX_CALLS) -> None:
        if not isinstance(key, Secret):
            raise CredentialsMissing("① 키는 Secret 이어야 합니다")
        self._key = key
        self._transport = transport or UrllibTransport()
        self._clock = clock or SystemClock()
        self._max_calls = max_calls
        self.calls = 0

    def __repr__(self) -> str:
        return f"ErpReader(calls={self.calls})"

    # ── 관문 ──────────────────────────────────────────────────────
    def _gate(self, method: str, path: str, params: Optional[Mapping[str, str]]) -> Tuple[int, bytes]:
        if method not in _ALLOWED_METHODS:
            raise ErpWriteForbidden(f"GET 이 아닌 요청은 만들지 않습니다: {method}")
        if path not in _PATHS:
            raise ErpWriteForbidden("허용하지 않은 경로")
        if params:
            if path != PATH_CONTRACTS or set(params) != {"stage", "has_contract"} \
                    or params["stage"] not in _ALL_SPELLINGS or params["has_contract"] != "true":
                raise ErpWriteForbidden("허용하지 않은 조회 조건")
        if self.calls >= self._max_calls:
            raise ErpIncomplete("call-cap", path)
        self.calls += 1
        headers = {"X-Api-Key": self._key.reveal(), "Accept": "application/json"}
        query = urllib.parse.urlencode(params) if params else ""
        url = BASE_URL + path + ("?" + query if query else "")
        req = urllib.request.Request(url, headers=headers, method=method)
        if req.get_method() != "GET" or req.data is not None:
            raise ErpWriteForbidden("GET 이 아닌 요청은 보내지 않습니다")
        if req.host != ERP_HOST or req.type != ERP_SCHEME:
            raise ErpWriteForbidden("허용하지 않은 호스트")
        del headers
        try:
            return self._transport.send(req, TIMEOUT)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise ErpError("network", path, None, type(e).__name__) from None
        except Exception as e:  # 뜻밖의 오류 — 문구에 키가 섞일 수 있어 종류 이름만 남긴다
            raise ErpError("other", path, None, type(e).__name__) from None

    def _get(self, path: str, params: Optional[Mapping[str, str]] = None) -> Any:
        status, body = self._gate("GET", path, params)
        if status != 200:
            raise ErpError("status", path, status)
        if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_BODY:
            raise ErpError("too-large", path, status)
        try:
            j = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ErpError("not-json", path, status) from None
        if not isinstance(j, dict) or j.get("status") != 200 or not isinstance(j.get("result"), dict):
            raise ErpError("bad-shape", path, status)
        return j["result"]

    # ── 계약 단계 ────────────────────────────────────────────────
    def read_stages(self) -> StageSnapshot:
        """7단계 × 표기 전부를 순서대로 부른다. 한 번이라도 실패하면 ``ErpIncomplete`` — 받은 것도 버린다."""
        by_pid: Dict[int, StageRow] = {}
        conflicts = set()
        per: Dict[str, int] = {}
        for key, spellings in STAGE_SPELLINGS.items():
            for spelling in spellings:
                try:
                    res = self._get(PATH_CONTRACTS, {"stage": spelling, "has_contract": "true"})
                except ErpError as e:
                    raise ErpIncomplete(e.kind, e.path, e.status, "단계 동기화 중단") from None
                items = res.get("items")
                total = res.get("total")
                if not isinstance(items, list) or isinstance(total, bool) or not isinstance(total, int) \
                        or total != len(items):
                    raise ErpIncomplete("bad-shape", PATH_CONTRACTS, 200, "단계 목록 모양")
                per[spelling] = len(items)
                for it in items:
                    row = self._stage_row(it, key)
                    old = by_pid.get(row.possibility_id)
                    if old is None:
                        if row.possibility_id not in conflicts:
                            by_pid[row.possibility_id] = row
                    elif old.stage_key != key:
                        conflicts.add(row.possibility_id)
                        del by_pid[row.possibility_id]
                    else:
                        raise ErpIncomplete("duplicate", PATH_CONTRACTS, 200, "같은 가망이 두 번")
        return StageSnapshot(by_pid, self._clock.now(), per, tuple(sorted(conflicts)))

    @staticmethod
    def _stage_row(it, key: str) -> StageRow:
        if not isinstance(it, Mapping):
            raise ErpIncomplete("bad-shape", PATH_CONTRACTS, 200, "줄 모양")
        pid = _pid(it.get("possibility_id"))
        if pid is None:
            raise ErpIncomplete("bad-shape", PATH_CONTRACTS, 200, "가망 번호")
        stage = it.get("stage")
        if not isinstance(stage, str) or _WS.sub("", stage) != key:
            raise ErpIncomplete("bad-shape", PATH_CONTRACTS, 200, "단계 이름이 요청과 다름")
        name = it.get("company_name")
        latest, unreadable = None, False
        contracts = it.get("contracts")
        if contracts is not None and not isinstance(contracts, list):
            raise ErpIncomplete("bad-shape", PATH_CONTRACTS, 200, "계약 줄 모양")
        for c in contracts or ():
            if not isinstance(c, Mapping):
                raise ErpIncomplete("bad-shape", PATH_CONTRACTS, 200, "계약 줄 모양")
            d, bad = _parse_date(c.get("end_date"))
            unreadable = unreadable or bad
            if d is not None and (latest is None or d > latest):
                latest = d
        return StageRow(pid, key, name if isinstance(name, str) else None, latest, unreadable)

    # ── 조직 스냅숏 · 네이버 고객 번호 ──────────────────────────────
    def read_org_snapshot(self) -> dict:
        """조직 스냅숏 원문(``result``) — 건전성 검사는 ``app.naver_auto.org_snapshot`` 이 한다."""
        return self._get(PATH_ORG_SNAPSHOT)

    def read_naver_customer_ids(self) -> Tuple[NaverIdRow, ...]:
        res = self._get(PATH_NAVER_IDS)
        items = res.get("items")
        if not isinstance(items, list):
            raise ErpIncomplete("bad-shape", PATH_NAVER_IDS, 200, "목록 모양")
        out: List[NaverIdRow] = []
        for it in items:
            if not isinstance(it, Mapping):
                raise ErpIncomplete("bad-shape", PATH_NAVER_IDS, 200, "줄 모양")
            pid = _pid(it.get("possibility_id"))
            if pid is None:
                raise ErpIncomplete("bad-shape", PATH_NAVER_IDS, 200, "가망 번호")
            vendor = it.get("vendor")
            raw = it.get("customer_id")
            out.append(NaverIdRow(pid, vendor if isinstance(vendor, str) else None,
                                  raw if isinstance(raw, str) else None))
        return tuple(out)


def handle_inputs(row: StageRow) -> Optional[Tuple[str, Optional[date]]]:
    """점검 손잡이 발급에 넘길 (단계, 가장 늦은 종료일). 종료일을 못 읽었으면 None — 발급하지 않는다."""
    if row.end_unreadable or row.stage_key not in H.MONITORED_STAGES:
        return None
    return row.stage_key, row.latest_end_date
