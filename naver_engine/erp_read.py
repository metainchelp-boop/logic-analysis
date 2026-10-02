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
from datetime import date, datetime, timedelta
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
PATH_ACCOUNT_CATALOG = "/api/ad-sync/naver-account-catalog"
_PATHS = frozenset({PATH_CONTRACTS, PATH_ORG_SNAPSHOT, PATH_NAVER_IDS, PATH_ACCOUNT_CATALOG})
_ALLOWED_METHODS = frozenset({"GET"})

# 엔진 전용 키(2026-09-29 대표 확정) — ③ 계약 동기화의 ERP_SYNC_API_KEY(= ① AD_SYNC_API_KEY)와 <b>다른</b> 값이다.
# ① 은 이 키의 지문(SHA-256)만 갖고, 조직도·고객 번호는 이 키로만 열린다(① ERP_CONTRACT_SYNC_API.md §11).
# 옛 키 이름은 일부러 읽지 않는다 — 옛 키로 돌면 ① 이 조직도·고객 번호를 거절해 「전부 아니면 버림」으로 멈춘다.
ENV_ERP_API_KEY = "NAVER_ENGINE_ERP_KEY"
KEY_MIN_LENGTH = 32                       # ① NaverEngineKeyVerifier.MIN_KEY_LENGTH 와 같다(짧으면 ① 이 대조하지 않는다)
KEY_MAX_LENGTH = 256
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
    """엔진 전용 키를 환경변수에서 읽는다. 없거나 · 32~256자가 아니거나 · 쓸 수 없는 글자가 있으면
    ``CredentialsMissing``(문구에 이름만 · 값 없음)."""
    src = os.environ if env is None else env
    raw = (src.get(ENV_ERP_API_KEY) or "").strip()
    if not raw:
        raise CredentialsMissing(f"① 키가 설정되지 않았습니다: {ENV_ERP_API_KEY}")
    if not re.fullmatch(r"[\x21-\x7e]+", raw):
        raise CredentialsMissing(f"{ENV_ERP_API_KEY} 에 쓸 수 없는 글자가 있습니다(빈칸·줄바꿈·한글 등)")
    if not KEY_MIN_LENGTH <= len(raw) <= KEY_MAX_LENGTH:
        raise CredentialsMissing(f"{ENV_ERP_API_KEY} 길이가 {KEY_MIN_LENGTH}~{KEY_MAX_LENGTH}자가 아닙니다")
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
    ad_account_no_raw: Optional[str] = field(default=None, repr=False)


def _display_text(v) -> bool:
    """저장소가 받는 글자인가 — 200자 이하 · NUL 없음 · UTF-8 로 쓸 수 있음."""
    if not isinstance(v, str) or len(v) > 200 or "\x00" in v:
        return False
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


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


def validate_account_catalog(body, now: datetime) -> dict:
    """전체 업체 존재 증거. 계약 단계별 부분 목록은 이 계약을 대신할 수 없다."""
    def bad():
        return ErpIncomplete("catalog-incomplete", PATH_ACCOUNT_CATALOG)
    if not isinstance(body, dict) or body.get("complete") is not True:
        raise bad()
    items, total = body.get("items"), body.get("total")
    if not isinstance(items, list) or type(total) is not int or total != len(items) or total > 250000:
        raise bad()
    try:
        at = datetime.fromisoformat(body["generated_at"])
    except (KeyError, TypeError, ValueError):
        raise bad() from None
    if at.tzinfo is None or not -timedelta(minutes=5) <= now-at <= H.STAGE_MAX_AGE:
        raise bad()
    clean, seen = [], set()
    for row in items:
        if not isinstance(row, dict):
            raise bad()
        pid = _pid(row.get("possibility_id"))
        name, stage = row.get("company_name"), row.get("stage")
        if pid is None or pid in seen or (name is not None and not _display_text(name)) or (stage is not None and not _display_text(stage)):
            raise bad()
        if type(row.get("stage_known")) is not bool or type(row.get("stage_hidden")) is not bool:
            raise bad()
        if row["stage_known"] and not stage:
            raise bad()
        seen.add(pid)
        clean.append({"possibility_id": pid, "company_name": name, "stage": stage,
                      "stage_known": row["stage_known"], "stage_hidden": row["stage_hidden"]})
    return {"generated_at": at.isoformat(), "total": total, "complete": True, "items": clean}


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
        except (ValueError, UnicodeDecodeError, RecursionError):   # 깊게 겹친 JSON 도 읽기 실패로(결과로 돌려주게)
            raise ErpError("not-json", path, status) from None
        if not isinstance(j, dict) or j.get("status") != 200 or not isinstance(j.get("result"), dict):
            raise ErpError("bad-shape", path, status)
        return j["result"]

    # ── 계약 단계 ────────────────────────────────────────────────
    def read_stages(self, deadline: Optional[datetime] = None) -> StageSnapshot:
        """7단계 × 표기 전부를 순서대로 부른다. 한 번이라도 실패하면 ``ErpIncomplete`` — 받은 것도 버린다.

        같은 단계의 **다른 표기**에서 같은 가망이 다시 나오면 한 줄로 합친다(① 이 빈칸 무시 매칭으로 바꾸면 두 표기가 같은
        목록을 준다 — 그것을 「중복」으로 버리면 동기화가 영영 멈춘다 · S7 적대 검토). 한 표기 응답 안에서 같은 번호가 두 번이면
        그때만 ``duplicate`` 다. ``deadline``(시간대 있는 시각)을 넘기면 남은 표기를 부르지 않고 ``ErpIncomplete("deadline")``
        — ② 04:00 · ③ 06:00 창에 읽기가 걸치지 않게(M3)."""
        by_pid: Dict[int, StageRow] = {}
        conflicts = set()
        per: Dict[str, int] = {}
        for key, spellings in STAGE_SPELLINGS.items():
            for spelling in spellings:
                if deadline is not None and self._clock.now() >= deadline:
                    raise ErpIncomplete("deadline", PATH_CONTRACTS, None, "읽기 마감")
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
                in_this = set()
                for it in items:
                    row = self._stage_row(it, key)
                    if row.possibility_id in in_this:
                        raise ErpIncomplete("duplicate", PATH_CONTRACTS, 200, "같은 가망이 두 번")
                    in_this.add(row.possibility_id)
                    old = by_pid.get(row.possibility_id)
                    if old is None:
                        if row.possibility_id not in conflicts:
                            by_pid[row.possibility_id] = row
                    elif old.stage_key != key:
                        conflicts.add(row.possibility_id)
                        del by_pid[row.possibility_id]
                    else:   # 같은 단계의 다른 표기 — 합친다(종료일은 늦은 쪽 · 못 읽음은 하나라도 · 이름은 먼저 것)
                        ends = [d for d in (old.latest_end_date, row.latest_end_date) if d is not None]
                        by_pid[row.possibility_id] = StageRow(
                            row.possibility_id, key, old.name if old.name is not None else row.name,
                            max(ends) if ends else None, old.end_unreadable or row.end_unreadable)
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
        if not _display_text(name):
            name = None   # 표시용 상호만 버린다(줄은 남긴다) — 이상한 상호 하나로 940곳 동기화가 멈추지 않게
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

    def read_account_catalog(self) -> dict:
        return validate_account_catalog(self._get(PATH_ACCOUNT_CATALOG), self._clock.now())

    def read_naver_customer_ids(self) -> Tuple[NaverIdRow, ...]:
        return self._naver_customer_id_rows(self._get(PATH_NAVER_IDS))

    @staticmethod
    def _naver_customer_id_rows(res) -> Tuple[NaverIdRow, ...]:
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
            if raw is not None and not isinstance(raw, str):
                raise ErpIncomplete("bad-shape", PATH_NAVER_IDS, 200, "고객 번호 모양")
            ad_no = it.get("ad_account_no")
            if ad_no is not None and not isinstance(ad_no, str):
                raise ErpIncomplete("bad-shape", PATH_NAVER_IDS, 200, "광고 계정 번호 모양")
            out.append(NaverIdRow(pid, vendor if isinstance(vendor, str) else None,
                                  raw, ad_no))
        return tuple(out)

    def read_naver_customer_ids_snapshot(self) -> Tuple[NaverIdRow, ...]:
        """전체 업체 분류용: 생성 후 2시간 이내 번호만 수락한다(시계 오차 5분).

        기존 번호 읽기는 시각을 요구하지 않는다. 이 경로만 같은 응답의 시각과 모든 행을
        검사하므로 catalog 갱신 중 실패한 번호 자료를 새 정상 자료로 캐시하지 않는다.
        """
        res = self._get(PATH_NAVER_IDS)
        try:
            at = datetime.fromisoformat(res["generated_at"])
        except (KeyError, TypeError, ValueError):
            raise ErpIncomplete("ids-snapshot-incomplete", PATH_NAVER_IDS) from None
        if at.tzinfo is None or not -timedelta(minutes=5) <= self._clock.now()-at <= timedelta(hours=2):
            raise ErpIncomplete("ids-snapshot-incomplete", PATH_NAVER_IDS)
        return self._naver_customer_id_rows(res)


def handle_inputs(row: StageRow) -> Optional[Tuple[str, Optional[date]]]:
    """점검 손잡이 발급에 넘길 (단계, 가장 늦은 종료일). 종료일을 못 읽었으면 None — 발급하지 않는다."""
    if row.end_unreadable or row.stage_key not in H.MONITORED_STAGES:
        return None
    return row.stage_key, row.latest_end_date
