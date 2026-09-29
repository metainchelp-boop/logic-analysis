"""① 전산 알림 관문 — 엔진이 ① 에 **넣는** 호출은 이 문 하나만 지난다(설계 v1.8 S10 · D6 비서방 · 대표 결정 A3).

읽기(``erp_read.py``)와 문을 나눈 까닭: 읽기 관문은 GET 만 만들고, 여기는 POST 만 만든다 — 한 관문이 두 방식을 갖지
않게(읽기 코드가 실수로 쓰기를 부를 길이 없게). 두 관문 모두 같은 호스트·같은 엔진 전용 키(``NAVER_ENGINE_ERP_KEY``)다.

지키는 것:
- **POST 만** · 호스트 ``api.metainc.co.kr`` 글자 그대로(``erp_read.ERP_HOST`` 하나) · 경로는 둘만 —
  비서방 알림 넣기(① 계약 문서 §12) · 「오늘 끝」 심박(§13 · 대표 결정 A3 — 08:10 까지 안 오면 ① 이 대표에게 알린다).
- 넘겨주기를 따라가지 않고 환경 프록시를 무시한다(``naver_read.UrllibTransport`` — 엔진에서 실제로 여는 곳은 그 하나).
- 키는 ``Secret`` 로만 들고, 꺼내는 곳은 이 관문 ``_gate`` 한 곳이다.
- **보내기 전에 ① 과 같은 규칙으로 검사한다**(§12.2) — 제목 한 줄 60자 · 줄 8개 × 120자 · 빈 줄·줄바꿈·보이지 않는 제어
  글자 금지 · 링크는 ``/naver/`` 안(``//``·``..``·``sso`` 금지) · 열쇠 8~64자. 어긋나면 ① 에 가지 않고 ``AlertRejected``
  (프로그램 결함 — 문구에 값 없음). 본문을 **만드는** 규칙(광고주 이름·금액·상품명을 싣지 않음)은 ``alerts.py`` 의 문구
  목록 한 곳이다 — 이 관문은 모양만 본다.
- **200 이 아니면 성공이 아니다** · 응답 모양(``status`` 200 · ``result``)과 ``reason`` 네 값만 받는다. 모르는 값은 실패.
- 문구·로그·예외에 키·제목·본문·열쇠를 싣지 않는다(개수·코드·상태 번호만).
- 호출 수 상한(① 하루 전체 상한 200 + 심박 + 여유) · 순서대로 한 번에 하나(① 은 같은 열쇠가 거의 동시에 오면 둘 다
  넣을 수 있다 — 엔진이 쓰는 곳이 하나라 순서대로 부른다).
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence, Tuple

from .credentials import CredentialsMissing, Secret
from .erp_read import BASE_URL, ERP_HOST, ERP_SCHEME
from .naver_read import UrllibTransport

log = logging.getLogger("naver_engine.erp_alert")

PATH_ALERTS = "/api/ad-sync/naver-alerts"
PATH_HEARTBEAT = "/api/ad-sync/naver-heartbeat"
_PATHS = frozenset({PATH_ALERTS, PATH_HEARTBEAT})
_ALLOWED_METHODS = frozenset({"POST"})
TIMEOUT = 15
MAX_REQUEST = 16 * 1024           # 알림 한 건의 본문 상한(제목 60 + 줄 8 × 120 자 — 넉넉히)
MAX_RESPONSE = 64 * 1024
MAX_CALLS = 260                   # 한 관문 객체 평생 — ① 하루 전체 상한 200 + 심박 + 여유

# ── ① 계약 §12.2 · §12.4 (① ``AdSyncNaverAlertService`` 와 같은 값 · 시험이 글자로 대조) ──
SEVERITY_NORMAL = "NORMAL"        # 비서방만
SEVERITY_URGENT = "URGENT"        # 비서방 + 전산 팝업
SEVERITIES = frozenset({SEVERITY_NORMAL, SEVERITY_URGENT})
TITLE_MAX = 60
LINE_MAX = 120
LINES_MAX = 8
LINK_MAX = 200
LINK_PREFIX = "/naver/"
_DEDUPE_KEY = re.compile(r"[A-Za-z0-9._:-]{8,64}")
_LINK = re.compile(r"/naver/[A-Za-z0-9/_.~?=&%#-]*")
# ① 이 거절하는 글자 종류(Java Character.getType CONTROL · FORMAT · LINE/PARAGRAPH_SEPARATOR · SURROGATE)
_BANNED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})
TARGET_MAX = 10 ** 15             # ① 직원 번호 — 0 = 대표 · 음수 불가

REASON_SENT = "sent"
REASON_DUPLICATE = "duplicate"
REASON_TARGET_CAP = "daily_cap_target"
REASON_TOTAL_CAP = "daily_cap_total"
REASONS = frozenset({REASON_SENT, REASON_DUPLICATE, REASON_TARGET_CAP, REASON_TOTAL_CAP})

HEARTBEAT_OK = "ok"               # 오늘 아침 일을 마쳤고 경보가 없었다
HEARTBEAT_TROUBLE = "trouble"     # 오늘 아침 일을 마쳤지만 경보가 있었다(대표에게는 엔진이 이미 알렸다)
HEARTBEAT_STATUSES = frozenset({HEARTBEAT_OK, HEARTBEAT_TROUBLE})


class AlertRejected(ValueError):
    """① 에 보내기 전 규칙 검사에서 걸림 — 프로그램 결함. 문구에 값(제목·열쇠·번호)을 싣지 않는다."""


class AlertSendError(RuntimeError):
    """① 호출 실패(네트워크 · 상태 · 응답 모양). 문구에 키·제목·본문을 싣지 않는다."""

    def __init__(self, kind: str, path: str, status: Optional[int] = None) -> None:
        self.kind, self.path, self.status = kind, path, status
        super().__init__(f"① 알림 실패 [{kind}] {path} 상태 {status}")

    @property
    def code(self) -> str:
        """저장소 오류 종류 칸에 넣을 코드 모양(숫자는 끝의 HTTP 상태 세 자리 하나만)."""
        if self.kind == "status" and isinstance(self.status, int) and 100 <= self.status <= 599:
            return f"status-{self.status}"
        return self.kind


class AlertWriteForbidden(RuntimeError):
    """POST 가 아닌 요청 · 허용하지 않은 경로·호스트."""


def _one_line(raw, limit: int, what: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise AlertRejected(f"{what} 칸이 비어 있습니다")
    v = raw.strip()
    if len(v) > limit:   # 파이썬 글자 수 = 코드 포인트 수(① codePointCount 와 같다)
        raise AlertRejected(f"{what} 칸이 {limit}자를 넘습니다")
    if any(unicodedata.category(ch) in _BANNED_CATEGORIES for ch in v):
        raise AlertRejected(f"{what} 칸에 줄바꿈이나 보이지 않는 제어 글자가 있습니다")
    return v


@dataclass(frozen=True)
class AlertPayload:
    """① 에 보낼 알림 한 건 — ``build_payload`` 가 검사해 만든다. ``repr`` 에는 받는 사람·중요도만."""
    target_emp_idx: int
    severity: str
    title: str
    lines: Tuple[str, ...]
    link_path: str
    dedupe_key: str

    def __repr__(self) -> str:
        return f"AlertPayload(target={self.target_emp_idx}, severity={self.severity}, lines={len(self.lines)})"

    def body(self) -> dict:
        return {"target_emp_idx": self.target_emp_idx, "severity": self.severity, "title": self.title,
                "lines": list(self.lines), "link_path": self.link_path, "dedupe_key": self.dedupe_key}


def build_payload(target_emp_idx, severity, title, lines: Sequence[str], link_path, dedupe_key) -> AlertPayload:
    """① 계약 §12.2 규칙 그대로 검사한다(① 보다 느슨하지 않게). 걸리면 ``AlertRejected``."""
    if isinstance(target_emp_idx, bool) or not isinstance(target_emp_idx, int) \
            or not 0 <= target_emp_idx < TARGET_MAX:
        raise AlertRejected("받는 사람 번호는 0 이상의 정수여야 합니다")
    if severity not in SEVERITIES:
        raise AlertRejected("중요도는 NORMAL · URGENT 중 하나여야 합니다")
    t = _one_line(title, TITLE_MAX, "제목")
    if isinstance(lines, (str, bytes)) or not isinstance(lines, (list, tuple)):
        raise AlertRejected("본문 줄은 목록이어야 합니다")
    if len(lines) > LINES_MAX:
        raise AlertRejected(f"본문 줄은 {LINES_MAX}줄 이하여야 합니다")
    ls = tuple(_one_line(x, LINE_MAX, "본문 줄") for x in lines)
    if not isinstance(link_path, str) or len(link_path) > LINK_MAX or not _LINK.fullmatch(link_path) \
            or "//" in link_path or ".." in link_path or "sso" in link_path.lower():
        raise AlertRejected("관제 화면 경로는 /naver/ 로 시작하는 짧은 경로여야 합니다")
    if not isinstance(dedupe_key, str) or not _DEDUPE_KEY.fullmatch(dedupe_key):
        raise AlertRejected("중복 방지 열쇠는 8~64자 영문·숫자·「. _ : -」여야 합니다")
    return AlertPayload(target_emp_idx, severity, t, ls, link_path, dedupe_key)


@dataclass(frozen=True)
class AlertResult:
    delivered: bool
    reason: str
    message_idx: Optional[int]


class ErpAlertPoster:
    """① 에 넣는 관문. 객체 하나를 한 번의 보내기 차례에 쓴다(호출 상한이 객체 평생 누적)."""

    def __init__(self, key: Secret, transport=None, max_calls: int = MAX_CALLS) -> None:
        if not isinstance(key, Secret):
            raise CredentialsMissing("① 키는 Secret 이어야 합니다")
        self._key = key
        self._transport = transport or UrllibTransport()
        self._max_calls = max_calls
        self.calls = 0

    def __repr__(self) -> str:
        return f"ErpAlertPoster(calls={self.calls})"

    # ── 관문 ──────────────────────────────────────────────────────
    def _gate(self, method: str, path: str, payload: dict) -> Tuple[int, bytes]:
        if method not in _ALLOWED_METHODS:
            raise AlertWriteForbidden(f"POST 가 아닌 요청은 만들지 않습니다: {method}")
        if path not in _PATHS:
            raise AlertWriteForbidden("허용하지 않은 경로")
        if not isinstance(payload, dict):
            raise AlertWriteForbidden("본문은 사전이어야 합니다")
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_REQUEST:
            raise AlertRejected("알림 본문이 너무 큽니다")
        if self.calls >= self._max_calls:
            raise AlertSendError("call-cap", path)
        self.calls += 1
        headers = {"X-Api-Key": self._key.reveal(), "Accept": "application/json",
                   "Content-Type": "application/json; charset=utf-8"}
        req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        if req.get_method() != "POST" or req.data is None:
            raise AlertWriteForbidden("POST 가 아닌 요청은 보내지 않습니다")
        if req.host != ERP_HOST or req.type != ERP_SCHEME or req.selector != path:
            raise AlertWriteForbidden("허용하지 않은 호스트")
        del headers
        try:
            return self._transport.send(req, TIMEOUT)
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise AlertSendError("network", path) from None
        except Exception:  # 뜻밖의 오류 — 문구에 키가 섞일 수 있어 종류만 남긴다
            raise AlertSendError("other", path) from None

    def _post(self, path: str, payload: dict) -> dict:
        status, body = self._gate("POST", path, payload)
        if status != 200:
            raise AlertSendError("status", path, status)
        if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_RESPONSE:
            raise AlertSendError("too-large", path, status)
        try:
            j = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise AlertSendError("not-json", path, status) from None
        if not isinstance(j, dict) or j.get("status") != 200 or not isinstance(j.get("result"), dict):
            raise AlertSendError("bad-shape", path, status)
        return j["result"]

    # ── 비서방 알림 넣기(① §12) ─────────────────────────────────────
    def send_alert(self, payload: AlertPayload) -> AlertResult:
        """한 사람에게 한 건. ① 이 넣지 않은 것(같은 열쇠 · 하루 상한)도 결과로 돌려준다 — 부르는 쪽이 기록한다."""
        if not isinstance(payload, AlertPayload):
            raise AlertRejected("알림은 build_payload 로 만든 것이어야 합니다")
        again = build_payload(payload.target_emp_idx, payload.severity, payload.title, payload.lines,
                              payload.link_path, payload.dedupe_key)   # 손으로 만든 객체도 한 번 더 검사
        res = self._post(PATH_ALERTS, again.body())
        delivered, reason, mid = res.get("delivered"), res.get("reason"), res.get("message_idx")
        if not isinstance(delivered, bool) or reason not in REASONS or delivered != (reason == REASON_SENT):
            raise AlertSendError("bad-shape", PATH_ALERTS, 200)
        if delivered:
            if isinstance(mid, bool) or not isinstance(mid, int) or mid <= 0:
                raise AlertSendError("bad-shape", PATH_ALERTS, 200)
        elif mid is not None:
            raise AlertSendError("bad-shape", PATH_ALERTS, 200)
        return AlertResult(delivered, reason, mid if delivered else None)

    # ── 「오늘 끝」 심박(① §13 · 대표 결정 A3) ───────────────────────
    def send_heartbeat(self, day: date, status: str) -> None:
        """오늘 아침 일을 마쳤다고 알린다(광고주 정보 0 — 날짜와 ok/trouble 만). ① 이 받았다고 답해야 성공이다."""
        if type(day) is not date:   # 시각(datetime)은 받지 않는다 — 날짜만
            raise AlertRejected("심박 날짜는 date 여야 합니다")
        if status not in HEARTBEAT_STATUSES:
            raise AlertRejected("심박 상태는 ok · trouble 중 하나여야 합니다")
        res = self._post(PATH_HEARTBEAT, {"day": day.isoformat(), "status": status})
        if res.get("recorded") is not True:
            raise AlertSendError("bad-shape", PATH_HEARTBEAT, 200)
