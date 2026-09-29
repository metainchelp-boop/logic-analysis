"""비서방 알림 — 무엇을 · 누구에게 · 언제 (설계 v1.8 S10 · §6 · D6 · M6 · Q4 · J5 · 대표 결정 A1 · A2 · A3 · I1 · I3).

알림 수단은 전산 메신저 「비서방」 하나(D6 · 휴대폰 알림 없음). ① 에 넣는 길은 알림 관문 ``erp_alert`` 하나다.

무엇을 · 누구에게
- **시스템 경보** — 동기화·짝 맞추기·점검 준비·아침 점검이 「알릴 것」(``alert``)을 내면 **대표에게 바로**(Q4 · 그림자 기간에도 ·
  주말에도). 같은 날 같은 「나온 곳:코드」는 한 번만. 점검을 통째로 멈추게 하는 코드와 대표 확인이 필요한 붙잡음은 긴급(팝업).
- **아침 요약(대표 결정 A1)** — 사람마다 하루 한 통 「오늘 확인할 광고주 N곳(🔴 a · 🟡 b)」. 🔴 는 긴급 받는 사람(담당 +
  가장 가까운 팀장 + 대표 · I1 ⓐ) · 🟡 는 주의 받는 사람(담당) — 받는 사람 규칙은 ``scope.alert_recipients`` 한 곳
  (불변식: 받는 사람 ⊆ 그 광고주를 여는 사람). 🔴 가 있으면 긴급(팝업). 점검은 08:00 전에 끝나고 직원은 그 뒤에 출근하므로
  🔴 도 이 한 통에 담는다(점검 회차마다 따로 보내면 한 사람이 아침에 여러 통을 받는다).
- **팀장 묶음(09:30)** — 🟡 광고주가 있는 팀원의 가장 가까운 팀장에게 「팀원 광고주 🟡 N곳」(``scope.digest_recipients``).
- **이관 받을 곳(매주 월요일 · I3 ⓐ)** — 한 번도 이관된 적 없는 광고주(짝 맞추기 막힘 ``not-linked``)를 담당에게 한 번.
- **그림자 요약(대표 결정 A2)** — 그림자 기간에는 광고주 이슈 알림(아침 요약 · 팀장 묶음 · 이관 목록)을 **보내지 않고 남겨만**
  둔다. 대신 대표에게 하루 한 통 — 점검 결과 개수 · 그림자가 끝났다면 몇 명에게 몇 통이 갔을지.
  그림자는 **날짜 + 스위치 둘 다** 켜져야 끝난다(``AlertPolicy`` — 하나라도 없으면 그림자).

언제(M6)
- 점검은 주말에도 돈다 · 메신저는 평일만 — 단 🔴 가 있는 요약과 시스템 경보는 주말에도 간다. 주말에 🟡 만 있는 요약은
  보내지 않고 남겨 둔다(관제 화면 🔔 에서 보인다 — S11). 공휴일은 따지지 않는다(설계 밖 · 필요하면 대표 결정).
- 아침 요약은 08:00 뒤 · 그날 점검 회차가 끝난 뒤(08:05 까지는 도는 회차를 기다린다) · 18:00 까지 못 만들면 그날은 건너뛴다.
- **「오늘 끝」 심박(대표 결정 A3)** — 아침 요약을 만들면 ① 에 날짜와 ok/trouble 만 보낸다. ① 이 08:10 까지 못 받으면
  대표 비서방에 긴급 한 통(① 쪽 일 · BE). 엔진이 죽거나 멈춰도 아무도 모르는 날이 없게.
  - 오늘 **끝난 점검 회차가 없으면**(멈춤 · 죽음 · 시작 못 함) 요약을 만든 뒤 대표에게 긴급 경보(``MORNING_NOT_DONE``)
    — 아침 점검·점검 준비가 이미 알린 날은 빼고. 그래서 점검 없는 날의 심박은 「정상」이 아니라 「trouble」이다.
  - 오늘 시스템 경보가 **모두 대표에게 들어간 뒤에만** 보낸다(trouble = 「이미 알렸다」). 못 넣었으면 보내지 않아 ① 감시가
    대신 알린다. 시스템 경보는 요약보다 먼저 보내고, 심박은 요약 줄보다 먼저 간다(요약이 수십 통이어도 08:10 전에).
- 12시간 안 풀린 🟡 를 한 단계 위로 올리기(v1.4)는 사람이 누르는 「확인」(S11 화면)과 함께 만든다 — 이 조각에는 없다.

지키는 것
- **본문은 문구 틀 + 숫자만** — 광고주 이름 · 금액 · 상품명 · 고객 번호를 싣지 않는다(설계 §6 · 대표 보안 지시). 저장소에는
  문구 틀 이름 · 코드 · 숫자 칸만 들어가고, 보낼 때 ``render`` 가 이 모듈의 문구로만 글자를 만든다.
- 받는 사람은 조직 수락본으로 계산한다. 조직이 낡았으면(26시간) 광고주 알림은 남겨만 두고 대표에게 시스템 경보.
  조직을 못 읽으면 시스템 경보는 대표 계정(0번)으로 간다.
- 보내기는 한 번에 하나 · 순서대로(① 은 같은 열쇠가 거의 동시에 오면 둘 다 넣을 수 있다). 못 보낸 것은 잠시 뒤 다시 ·
  다섯 번(시스템 경보는 횟수로 그만두지 않고 30분 간격으로) · 12시간이 지나면 그만(어제 요약이 오늘 가지 않게). ① 이 넣지
  않은 것(같은 열쇠 · 하루 상한)도 결과로 남긴다. 400(그 줄만의 문제) 말고는 — 키 거절 · 상한 · 네트워크 · 서버 오류 —
  그 차례의 나머지를 부르지 않는다(느린 ① 에 줄마다 기다리지 않게). 12시간 동안 못 보낸 시스템 경보는 알린 것으로 치지
  않아 같은 코드가 다시 나면 새로 알린다.
- 결과는 예외가 아니라 ``*Outcome`` 으로(개수·코드만) · 저장소 자체 오류(``StoreError``)는 그대로 던진다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.naver_auto import org_snapshot as O
from app.naver_auto import scope as SC
from app.naver_auto import verdict as V

from . import erp_alert as EA
from . import links as L
from . import morning as MO
from . import store as S
from . import sync as Y

KST = S.KST
DIGEST_AT = time(8, 0)                  # 아침 요약 — 점검 마감(08:00) 뒤(대표 결정 A1)
DIGEST_WAIT_UNTIL = time(8, 5)          # 이때까지는 도는 점검 회차가 끝나기를 기다린다(심박이 ① 08:10 감시 전에 가게)
LEAD_DIGEST_AT = time(9, 30)            # 팀장 🟡 묶음(설계 §6)
COMPOSE_UNTIL = time(18, 0)             # 이때까지 못 만든 요약은 그날 건너뛴다
WEEKLY_WEEKDAY = 0                      # 월요일(I3 ⓐ)
RETRY_BACKOFF = (timedelta(minutes=2), timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=30))
MAX_ATTEMPTS = len(RETRY_BACKOFF) + 1   # 다섯 번
HEARTBEAT_RETRY = timedelta(minutes=2)
DISPATCH_LIMIT = 200                    # 한 차례에 보내 볼 줄 수(① 하루 전체 상한과 같다)
ISSUE_OPEN = frozenset({"new", "ack"})  # 「확인할 일」 — 🆕 · 👀(예외 🙈 는 빼고)

LINK_HOME = "/naver/"
LINK_ISSUES = "/naver/issues"
LINK_SYSTEM = "/naver/system"
LINK_UNLINKED = "/naver/unlinked"

SEV_NORMAL, SEV_URGENT = EA.SEVERITY_NORMAL, EA.SEVERITY_URGENT
CODE_NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"   # 붙잡아 둔 목록 — 대표 확인이 필요하다(코드로 싣는다)
CODE_ORG_UNAVAILABLE = "ORG_UNAVAILABLE"         # 조직을 못 읽어 받는 사람을 계산하지 못함
CODE_ORG_STALE = "ORG_STALE"                     # 조직이 낡아 광고주 알림을 남겨만 둠
CODE_OTHER = "OTHER_CODE"                        # 코드 모양이 아닌 코드(기록에 싣지 않는다)
CODE_MORNING_NOT_DONE = "MORNING_NOT_DONE"       # 아침 요약을 만들 때까지 오늘 끝난 점검 회차가 없음(멈춤·시작 못 함)
SOURCE_OF_SYNC = {S.SYNC_ORG: "org", S.SYNC_STAGES: "stages", S.SYNC_ACCOUNTS: "accounts"}

# 점검을 통째로 멈추거나(오늘 점검 없음) 광고주 여럿에 걸친 경보 — 긴급(팝업)
URGENT_CODES = frozenset({MO.CODE_ACCOUNTS_UNUSABLE, MO.CODE_PAIRING_NOT_TODAY, MO.CODE_NOT_READY_LATE,
                          MO.CODE_RUNS_EXHAUSTED, MO.CODE_RUN_ABORT, MO.CODE_KEY_REJECTED_ALL,
                          MO.CODE_KEY_REJECTED_MANY, MO.CODE_NAVER_UNAVAILABLE, MO.CODE_DEADLINE_CUT,
                          MO.CODE_UNLINK_MASS, CODE_NEEDS_CONFIRMATION, CODE_ORG_UNAVAILABLE,
                          CODE_MORNING_NOT_DONE})

SOURCE_NAMES = {"org": "조직 동기화", "stages": "계약 단계 동기화", "accounts": "대행 연결 목록 받기",
                "pairing": "짝 맞추기", "readiness": "점검 준비", "morning": "아침 점검", "compose": "알림 만들기"}

# 코드 → 한 줄(광고주 이름·번호 없음). 모르는 코드는 「그 밖의 경보 (코드)」.
CODE_TEXT = {
    CODE_NEEDS_CONFIRMATION: "대표님 확인이 필요한 목록이 있습니다(관제 › 시스템)",
    CODE_ORG_UNAVAILABLE: "조직 자료를 읽지 못해 받는 사람을 계산하지 못했습니다",
    CODE_ORG_STALE: "조직 자료가 낡아 광고주 알림을 보내지 않고 남겨 두었습니다",
    CODE_MORNING_NOT_DONE: "오늘 아침 점검이 끝나지 않았습니다(멈췄거나 시작하지 못함)",
    MO.CODE_ACCOUNTS_UNUSABLE: "대행 연결 목록을 쓸 수 없어 점검이 멈췄습니다",
    MO.CODE_PAIRING_NOT_TODAY: "오늘 짝 맞추기가 없습니다",
    MO.CODE_PAIRING_STALE: "짝 맞추기가 지금 자료와 달라 다시 맞추기를 기다립니다",
    MO.CODE_ACCOUNTS_STEP_PENDING: "오늘 대행 연결 목록을 아직 받지 못했습니다",
    MO.CODE_NOT_READY_LATE: "07:30 까지 점검 준비가 끝나지 않았습니다",
    MO.CODE_RUNS_EXHAUSTED: "오늘 점검을 세 번 다 돌았습니다",
    MO.CODE_RUN_ABORT: "호출 상한·속도 제한으로 회차가 멈췄습니다",
    MO.CODE_KEY_REJECTED_ALL: "네이버가 키를 모두 거절해 점검을 멈췄습니다",
    MO.CODE_KEY_REJECTED_MANY: "네이버 키 거절이 몰려 점검을 멈췄습니다",
    MO.CODE_DEADLINE_CUT: "08:00 까지 다 돌지 못한 광고주가 있습니다(점검 안 됨)",
    MO.CODE_SYSTEM_GAP: "우리 쪽 자료 문제로 점검하지 못한 광고주가 있습니다",
    MO.CODE_SHAPE_UNKNOWN: "네이버 응답 모양이 달라 판정하지 않은 광고주가 있습니다",
    MO.CODE_PAIR_DUPLICATE: "한 계정이 두 광고주에 이어져 점검하지 않았습니다",
    MO.CODE_UNLINK_MASS: "짝이 한꺼번에 많이 사라져 이슈를 많이 닫았습니다",
    MO.CODE_STORE_REFUSED: "저장소가 결과를 받지 않았습니다",
    MO.CODE_HANDLE_INVALID: "관리계정 손잡이를 쓸 수 없습니다",
    MO.CODE_UNEXPECTED: "뜻밖의 오류가 있었습니다",
    MO.CODE_DATA_LATE: "네이버 자료가 늦어 일부 규칙을 못 돌린 광고주가 있습니다",
    MO.CODE_NAVER_UNAVAILABLE: "네이버 서버·네트워크 오류가 몰려 점검을 멈췄습니다",
    MO.CODE_RUN_ORPHANED: "닫히지 못한 점검 회차를 실패로 닫았습니다",
    MO.CODE_ACCOUNT_ERROR: "한 계정에서 뜻밖의 오류가 있었습니다(그 계정만 점검 안 됨)",
    Y.CODE_IMPLAUSIBLE_FIRST: "첫 계약 단계 목록의 광고주 수가 예상과 크게 다릅니다",
    Y.CODE_STAGE_EMPTY_FIRST: "첫 계약 단계 목록에 비어 있는 단계가 있습니다",
    Y.CODE_STORED_UNREADABLE: "저장된 조직 자료를 읽지 못했습니다",
    Y.CODE_ACTIVE_DROP_BASELINE: "재직자 수가 기준보다 크게 줄었습니다",
    Y.CODE_OWNER_DROP_BASELINE: "담당 줄 수가 기준보다 크게 줄었습니다",
    Y.CODE_MANAGER_SPIKE_BASELINE: "팀장 수가 기준보다 크게 줄었습니다",
    S.BRAKE_TOTAL: "목록이 한꺼번에 크게 줄어 받지 않았습니다",
    S.BRAKE_STAGE: "한 단계 목록이 크게 줄어 받지 않았습니다",
    S.BRAKE_BASELINE: "목록이 기준보다 조금씩 크게 줄어 받지 않았습니다",
    S.BRAKE_MANAGER: "관리계정 목록이 크게 달라져 받지 않았습니다",
    S.BRAKE_CONFIRMED: "확인한 짝의 계정이 한꺼번에 빠져 받지 않았습니다",
    L.CODE_INCOMPLETE: "네이버 연결 목록을 전부 받지 못했습니다",
    L.CODE_ACCOUNTS_NONE: "대행 연결 목록을 한 번도 받지 못했습니다",
    L.CODE_ACCOUNTS_STALE: "대행 연결 목록이 낡았습니다",
    L.CODE_STAGES_NONE: "계약 단계를 한 번도 받지 못했습니다",
    L.CODE_STAGES_STALE: "계약 단계 자료가 낡았습니다",
    L.CODE_BAD_INPUT: "짝 맞추기가 입력을 받지 않았습니다",
    L.CODE_CLOCK_BEHIND: "저장된 시각이 지금보다 미래입니다(시계 확인)",
    "network": "전산·네이버에 연결하지 못했습니다",
    "status-401": "키를 거절당했습니다(401)",
    "status-403": "권한을 거절당했습니다(403)",
    "deadline": "읽기 마감 시각을 넘겨 멈췄습니다",
}


class RenderError(ValueError):
    """저장된 알림을 문구로 만들 수 없음(모르는 문구 틀 · 빠진 숫자) — 프로그램 결함."""


@dataclass(frozen=True)
class AlertPolicy:
    """그림자 운영 — **날짜와 스위치 둘 다** 있어야 광고주 이슈 알림을 보낸다(설계 바뀐 순서 10). 시스템 경보는 늘 간다(Q4)."""
    issue_alerts_from: Optional[date] = None
    issue_alerts_on: bool = False

    def __post_init__(self) -> None:
        if self.issue_alerts_from is not None and type(self.issue_alerts_from) is not date:
            raise ValueError("issue_alerts_from 은 날짜(date)여야 합니다")
        if type(self.issue_alerts_on) is not bool:
            raise ValueError("issue_alerts_on 은 참/거짓이어야 합니다")

    def in_shadow(self, day: date) -> bool:
        return not (self.issue_alerts_on and self.issue_alerts_from is not None and day >= self.issue_alerts_from)


SHADOW = AlertPolicy()


@dataclass(frozen=True)
class ComposeOutcome:
    made: Tuple[str, ...] = ()                                               # 만든 알림 종류
    counts: Dict[str, int] = field(default_factory=dict, compare=False)      # 받는 사람 줄 상태별

    def __repr__(self) -> str:
        return f"ComposeOutcome(made={list(self.made)}, counts={dict(sorted(self.counts.items()))})"


@dataclass(frozen=True)
class DispatchOutcome:
    counts: Dict[str, int] = field(default_factory=dict)                     # 결과별(sent · duplicate · retry · failed …)
    stopped: Optional[str] = None                                            # 차례를 멈춘 까닭(키 거절 · 상한)

    def __repr__(self) -> str:
        return f"DispatchOutcome(counts={dict(sorted(self.counts.items()))}, stopped={self.stopped})"


@dataclass(frozen=True)
class HeartbeatOutcome:
    sent: bool
    status: Optional[str] = None
    error: Optional[str] = None


def _need_time(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 합니다")


def _local(now: datetime) -> datetime:
    return now.astimezone(KST)


def _weekend(day: date) -> bool:
    return day.weekday() >= 5


# ── 조직 · 받는 사람 ─────────────────────────────────────────────────
def _org(store: S.Store, now: datetime) -> Tuple[Optional[O.Org], bool]:
    """(조직, 쓸 수 있음). 못 읽으면 (None, False) · 낡았으면 (조직, False)."""
    try:
        stored = store.org_current()
        if stored is None:
            return None, False
        org = O.parse_org_snapshot(stored["body"])
    except (S.StoreError, O.SnapshotFormatError):
        return None, False
    return org, O.allows_raising(Y.org_freshness(store, now))


def ceo_recipients(org: Optional[O.Org]) -> frozenset:
    """시스템 경보 받는 사람 — 재직 중인 대표. 조직을 못 읽거나 대표가 없으면 대표 계정 0번(① 실측 · 설계 v1.6)."""
    top = org.top_managers() if org is not None else frozenset()
    return top or frozenset({O.REPRESENTATIVE_EMPLOYEE_IDX})


def _ownership(org: O.Org, possibility_id: int) -> SC.Ownership:
    return SC.ownership_for_client(org, possibility_id, possibility_id, SC.MATCH_PID)


# ── 문구 ────────────────────────────────────────────────────────────
def _code_line(code: str) -> str:
    return CODE_TEXT.get(code) or f"그 밖의 경보 ({code})"


def _need(params: Mapping, *names) -> Tuple[int, ...]:
    out = []
    for n in names:
        v = params.get(n)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise RenderError("숫자 칸이 빠졌습니다")
        out.append(v)
    return tuple(out)


def render(template: str, source: str, codes: Sequence[str], params: Mapping) -> Tuple[str, Tuple[str, ...]]:
    """저장된 문구 틀 · 코드 · 숫자 → (제목, 줄). 글자는 이 모듈의 문구뿐이다(광고주 이름·금액·번호가 들어갈 자리가 없다)."""
    if template == "system":
        title = f"시스템 경보 — {SOURCE_NAMES.get(source, '엔진')}"
        lines = [_code_line(c) for c in codes]
        if not lines:
            raise RenderError("경보 코드가 없습니다")
        if len(lines) > EA.LINES_MAX:
            lines = lines[:EA.LINES_MAX - 1] + [f"그 밖 {len(lines) - (EA.LINES_MAX - 1)}건"]
        return title, tuple(lines)
    if template == "digest":
        red, yellow = _need(params, "red", "yellow")
        return (f"오늘 확인할 광고주 {red + yellow}곳",
                (f"🔴 긴급 {red}곳 · 🟡 주의 {yellow}곳", "관제 화면에서 확인해 주세요"))
    if template == "lead_digest":
        count, people = _need(params, "count", "people")
        return (f"팀원 광고주 🟡 주의 {count}곳", (f"담당 {people}명의 광고주입니다", "관제 화면에서 확인해 주세요"))
    if template == "weekly_unlinked":
        (count,) = _need(params, "count")
        return (f"이관 받을 곳 {count}곳", ("한 번도 이관된 적 없는 광고주입니다",
                                         "관제 화면 「이관 안 됨」에서 확인해 주세요"))
    if template == "shadow_summary":
        ok, part, miss, link, red, yellow, new, auto, people, msgs = _need(
            params, "ok", "partial", "missed", "link", "red", "yellow", "new", "auto", "people", "msgs")
        return ("그림자 운영 — 오늘 아침 점검 요약",
                (f"점검 끝 {ok}곳 · 일부·늦음 {part}곳 · 못 함 {miss}곳 · 이관 {link}곳",
                 f"확인할 광고주 🔴 {red}곳 · 🟡 {yellow}곳",
                 f"새 이슈 {new}건 · 저절로 풀림 {auto}건",
                 f"그림자가 끝났다면 {people}명에게 {msgs}통",
                 "광고주 이슈 알림은 그림자 기간에 보내지 않습니다"))
    raise RenderError("모르는 문구 틀입니다")


# ── 시스템 경보(대표 · 바로 · 그림자·주말에도) ───────────────────────
def _clean_codes(codes: Iterable) -> List[str]:
    out = []
    for c in codes:
        c = c if isinstance(c, str) and S.ERROR_CODE.fullmatch(c) else CODE_OTHER
        if c not in out:
            out.append(c)
    return out


def record_system_alert(store: S.Store, now: datetime, source: str, codes: Iterable[str],
                        needs_confirmation: bool = False) -> Optional[int]:
    """대표에게 시스템 경보 — 오늘 아직 알리지 않은 「나온 곳:코드」만. 새 코드가 없으면 None(되풀이하지 않는다)."""
    _need_time(now)
    if source not in SOURCE_NAMES:
        raise ValueError("알림이 나온 곳이 아닙니다")
    cs = _clean_codes(codes)
    if needs_confirmation and CODE_NEEDS_CONFIRMATION not in cs:
        cs.insert(0, CODE_NEEDS_CONFIRMATION)
    if not cs:
        cs = [CODE_OTHER]
    today = _local(now).date()
    seen = store.system_alert_keys_on(today)
    new = [c for c in cs if f"{source}:{c}" not in seen][:S.MAX_SYNC_CODES]
    if not new:
        return None
    org, _usable = _org(store, now)
    sev = SEV_URGENT if set(new) & URGENT_CODES else SEV_NORMAL
    people = [{"emp_idx": p, "severity": sev, "params": {}} for p in sorted(ceo_recipients(org))]
    return store.record_alert(S.ALERT_SYSTEM, today, source, "system", new, LINK_SYSTEM, people, now)


def note(store: S.Store, now: datetime, result) -> Optional[int]:
    """엔진 결과 하나를 보고 알릴 것이 있으면 시스템 경보를 적는다 — 스케줄러가 결과마다 부른다.

    - 동기화(``SyncResult``) · 짝 맞추기(``PairingOutcome``) · 아침 점검(``MorningOutcome``) = ``alert`` 가 참일 때만.
    - 점검 준비(``Readiness``) = 연결 목록 못 씀은 바로 · 막힘 코드는 07:30 「준비 늦음」과 함께만(짝 맞추기를 기다리는 잠깐을
      경보로 올리지 않게). 오늘 끝난 회차가 있으면 연결 목록 못 씀만(끝난 뒤 들어온 단계 자료로 생긴 막힘은 내일 일이다)."""
    _need_time(now)
    if isinstance(result, Y.SyncResult):
        if not result.alert:
            return None
        return record_system_alert(store, now, SOURCE_OF_SYNC.get(result.kind, "org"), result.codes,
                                   needs_confirmation=result.needs_confirmation)
    if isinstance(result, L.PairingOutcome):
        return record_system_alert(store, now, "pairing", result.codes) if result.alert else None
    if isinstance(result, MO.MorningOutcome):
        if not result.alert:
            return None
        return record_system_alert(store, now, "morning", [c for c in result.codes if c in MO.ALERTING] or result.codes)
    if isinstance(result, MO.Readiness):
        codes = set(result.codes)
        today = _local(now).date()
        done = any(r["status"] == S.RUN_DONE for r in store.runs_on(today))
        send = codes & {MO.CODE_ACCOUNTS_UNUSABLE}
        if not done and MO.CODE_NOT_READY_LATE in codes:
            send |= {MO.CODE_NOT_READY_LATE} | (codes & MO.BLOCKING)
        order = [c for c in result.codes if c in send]
        return record_system_alert(store, now, "readiness", order) if order else None
    raise TypeError("알 수 없는 결과 모양입니다")


# ── 요약 만들기 ─────────────────────────────────────────────────────
def _open_issue_levels(store: S.Store) -> Dict[int, str]:
    """가망 → 가장 높은 열린 등급(red · yellow) — 🆕 · 👀 만(예외 🙈 · ⓘ 는 빼고)."""
    out: Dict[int, str] = {}
    for i in store.issues(open_only=True):
        if i["state"] not in ISSUE_OPEN or i["severity"] not in ("red", "yellow"):
            continue
        pid = i["possibility_id"]
        if out.get(pid) != "red":
            out[pid] = i["severity"]
    return out


def _person_counts(org: O.Org, levels: Mapping[int, str]) -> Dict[int, Counter]:
    per: Dict[int, Counter] = {}
    for pid, lvl in levels.items():
        own = _ownership(org, pid)
        who = SC.alert_recipients(org, own, SC.URGENT if lvl == "red" else SC.CAUTION)
        for p in who:
            per.setdefault(p, Counter())[lvl] += 1
    return per


def _held(day: date, policy: AlertPolicy, usable: bool, urgent: bool) -> Optional[str]:
    if not usable:
        return "org_stale"
    if _weekend(day) and not urgent:
        return "weekend"
    if policy.in_shadow(day):
        return "shadow"
    return None


def _running_fresh(store: S.Store, today: date, now: datetime) -> bool:
    """오늘 도는 점검 회차가 있나(08:05 까지만 기다린다 — 멈춘 회차로 요약·심박이 막히지 않게)."""
    if _local(now).time() >= DIGEST_WAIT_UNTIL:
        return False
    return any(r["status"] == S.RUN_RUNNING for r in store.runs_on(today))


def _made(store: S.Store, today: date, kind: str) -> bool:
    return bool(store.alerts_on(today, kind))


def compose_due(store: S.Store, now: datetime, policy: AlertPolicy = SHADOW) -> Tuple[str, ...]:
    """지금 만들 요약 종류(순서대로) — 아침 요약 → 이관 목록(월) → 그림자 요약 → 팀장 묶음(09:30)."""
    _need_time(now)
    local = _local(now)
    today, t = local.date(), local.time()
    if not DIGEST_AT <= t < COMPOSE_UNTIL:
        return ()
    out = []
    morning_ok = not _running_fresh(store, today, now)
    if morning_ok and not _made(store, today, S.ALERT_DIGEST):
        out.append(S.ALERT_DIGEST)
    if morning_ok and today.weekday() == WEEKLY_WEEKDAY and not _made(store, today, S.ALERT_WEEKLY_UNLINKED):
        out.append(S.ALERT_WEEKLY_UNLINKED)
    if morning_ok and policy.in_shadow(today) and not _made(store, today, S.ALERT_SHADOW_SUMMARY):
        out.append(S.ALERT_SHADOW_SUMMARY)
    if t >= LEAD_DIGEST_AT and not _made(store, today, S.ALERT_LEAD_DIGEST):
        out.append(S.ALERT_LEAD_DIGEST)
    return tuple(out)


def _record(store: S.Store, kind: str, today: date, template: str, link: str, people: List[dict],
            now: datetime) -> Counter:
    try:
        aid = store.record_alert(kind, today, "compose", template, (), link, people, now)
    except S.AlertExists:
        return Counter()
    return Counter(r["status"] for r in store.alert_recipients(aid))


def _digest(store: S.Store, now: datetime, policy: AlertPolicy, org: Optional[O.Org], usable: bool) -> Counter:
    today = _local(now).date()
    people = []
    if org is not None:
        for p, c in sorted(_person_counts(org, _open_issue_levels(store)).items()):
            red, yellow = c.get("red", 0), c.get("yellow", 0)
            urgent = red > 0
            people.append({"emp_idx": p, "severity": SEV_URGENT if urgent else SEV_NORMAL,
                           "params": {"red": red, "yellow": yellow},
                           "held_reason": _held(today, policy, usable, urgent)})
    return _record(store, S.ALERT_DIGEST, today, "digest", LINK_ISSUES, people, now)


def _lead_counts(store: S.Store, org: O.Org) -> Dict[int, List]:
    """팀장 → [🟡 광고주 수, 담당 번호들] — 팀장 묶음과 그림자 요약이 같은 셈을 쓴다."""
    per: Dict[int, List] = {}
    for pid, lvl in _open_issue_levels(store).items():
        if lvl != "yellow":
            continue   # 🔴 는 아침 요약에서 팀장이 이미 받았다
        own = _ownership(org, pid)
        for lead in SC.digest_recipients(org, own):
            per.setdefault(lead, [0, set()])
            per[lead][0] += 1
            per[lead][1].add(own.main)
    return per


def _lead_digest(store: S.Store, now: datetime, policy: AlertPolicy, org: Optional[O.Org], usable: bool) -> Counter:
    today = _local(now).date()
    people = []
    if org is not None:
        for lead, (count, mains) in sorted(_lead_counts(store, org).items()):
            people.append({"emp_idx": lead, "severity": SEV_NORMAL,
                           "params": {"count": count, "people": len(mains)},
                           "held_reason": _held(today, policy, usable, False)})
    return _record(store, S.ALERT_LEAD_DIGEST, today, "lead_digest", LINK_ISSUES, people, now)


def _weekly_unlinked(store: S.Store, now: datetime, policy: AlertPolicy, org: Optional[O.Org],
                     usable: bool) -> Counter:
    today = _local(now).date()
    people = []
    last = store.last_pairing(S.SYNC_ACCEPTED)
    if org is not None and last is not None:
        pids = sorted({r["possibility_id"] for r in store.pairing_rows(last["pairing_id"])
                       if r["state"] == S.PAIR_BLOCKED and r["code"] == "not-linked"})
        per: Counter = Counter()
        for pid in pids:
            for p in SC.alert_recipients(org, _ownership(org, pid), SC.CAUTION):
                per[p] += 1
        for p, n in sorted(per.items()):
            people.append({"emp_idx": p, "severity": SEV_NORMAL, "params": {"count": n},
                           "held_reason": _held(today, policy, usable, False)})
    return _record(store, S.ALERT_WEEKLY_UNLINKED, today, "weekly_unlinked", LINK_UNLINKED, people, now)


def _shadow_summary(store: S.Store, now: datetime, policy: AlertPolicy, org: Optional[O.Org], usable: bool) -> Counter:
    today = _local(now).date()
    st = Counter(store.account_days_on(today).values())
    ev = store.issue_event_counts_on(today)
    levels = Counter(_open_issue_levels(store).values())
    would = Counter()
    for kind in (S.ALERT_DIGEST, S.ALERT_WEEKLY_UNLINKED):
        for a in store.alerts_on(today, kind):
            for r in store.alert_recipients(a["alert_id"]):
                if r["held_reason"] == "shadow":
                    would[r["emp_idx"]] += 1
    if org is not None and _held(today, policy, usable, False) == "shadow":
        for lead in _lead_counts(store, org):   # 09:30 팀장 묶음은 아직 안 만들어졌다 — 같은 셈으로 미리 센다
            would[lead] += 1
    params = {
        "ok": st.get(V.CHECK_OK, 0),
        "partial": st.get(V.CHECK_PARTIAL, 0) + st.get(V.CHECK_DATA_LATE, 0),
        "missed": st.get(V.CHECK_NOT_CHECKED, 0) + st.get(V.CHECK_KEY_REJECTED, 0) + st.get(V.CHECK_SYSTEM_GAP, 0)
        + st.get(V.CHECK_NOT_ELIGIBLE, 0),
        "link": st.get(V.CHECK_LINK_BROKEN, 0) + st.get(V.CHECK_LINK_MISSING, 0),
        "red": levels.get("red", 0), "yellow": levels.get("yellow", 0),
        "new": ev.get("opened", 0) + ev.get("reappeared", 0), "auto": ev.get("auto_resolved", 0),
        "people": len(would), "msgs": sum(would.values()),
    }
    urgent = params["red"] > 0
    held = "weekend" if _weekend(today) and not urgent else None   # 대표에게 가는 요약 — 조직이 낡아도 보낸다
    people = [{"emp_idx": p, "severity": SEV_NORMAL, "params": params, "held_reason": held}
              for p in sorted(ceo_recipients(org))]
    return _record(store, S.ALERT_SHADOW_SUMMARY, today, "shadow_summary", LINK_HOME, people, now)


def compose(store: S.Store, now: datetime, policy: AlertPolicy = SHADOW) -> ComposeOutcome:
    """지금 만들 요약을 만든다(없으면 아무것도 안 함). 조직을 못 읽거나 낡았으면 대표에게 시스템 경보 한 번."""
    _need_time(now)
    if not isinstance(policy, AlertPolicy):
        raise TypeError("policy 는 AlertPolicy 여야 합니다")
    due = compose_due(store, now, policy)
    if not due:
        return ComposeOutcome()
    org, usable = _org(store, now)
    if org is None:
        record_system_alert(store, now, "compose", [CODE_ORG_UNAVAILABLE])
    elif not usable:
        record_system_alert(store, now, "compose", [CODE_ORG_STALE])
    total: Counter = Counter()
    for kind in due:
        if kind == S.ALERT_DIGEST:
            total += _digest(store, now, policy, org, usable)
        elif kind == S.ALERT_WEEKLY_UNLINKED:
            total += _weekly_unlinked(store, now, policy, org, usable)
        elif kind == S.ALERT_SHADOW_SUMMARY:
            total += _shadow_summary(store, now, policy, org, usable)
        elif kind == S.ALERT_LEAD_DIGEST:
            total += _lead_digest(store, now, policy, org, usable)
    return ComposeOutcome(due, dict(total))


# ── 보내기 ──────────────────────────────────────────────────────────
def _backoff(attempts_after: int, until_expiry: bool = False) -> Optional[timedelta]:
    """이번까지 시도 수 → 다음에 해 볼 간격(다섯 번째면 None = 그만). 시스템 경보는 횟수로 그만두지 않고 30분 간격으로
    기한(12시간)까지 — ① 이 한 시간 멈춘 날 대표 경보가 조용히 버려지지 않게(검토 trouble-heartbeat-masks)."""
    if attempts_after >= MAX_ATTEMPTS and not until_expiry:
        return None
    return RETRY_BACKOFF[min(attempts_after, len(RETRY_BACKOFF)) - 1]


def _retry_or_fail(store: S.Store, row: dict, now: datetime, code: str) -> str:
    gap = _backoff(row["attempts"] + 1, until_expiry=row["kind"] == S.ALERT_SYSTEM)
    if gap is None:
        store.record_delivery(row["recipient_id"], S.DELIVERY_FAILED, now, error_kind=code)
        return "failed"
    store.record_delivery(row["recipient_id"], S.DELIVERY_PENDING, now, error_kind=code, next_try_at=now + gap)
    return "retry"


_REASON_STATUS = {EA.REASON_SENT: S.DELIVERY_SENT, EA.REASON_DUPLICATE: S.DELIVERY_DUPLICATE,
                  EA.REASON_TARGET_CAP: S.DELIVERY_CAP_TARGET, EA.REASON_TOTAL_CAP: S.DELIVERY_CAP_TOTAL}
def dispatch(store: S.Store, now: datetime, poster: EA.ErpAlertPoster, limit: int = DISPATCH_LIMIT,
             kind: Optional[str] = None) -> DispatchOutcome:
    """보낼 때가 된 줄을 한 번에 하나씩 ① 에 넣고 결과를 적는다(``kind`` 를 주면 그 종류만).

    ① 이 400(이 줄만의 문제 — 퇴사 등)이 아닌 까닭으로 못 받으면(키 거절 · 호출 상한 · 네트워크 · 서버 오류) 그 차례의
    나머지는 부르지 않는다 — 느린 ① 에 줄마다 기다려 심박이 08:10 뒤로 밀리지 않게(검토 heartbeat-queued)."""
    _need_time(now)
    if not isinstance(poster, EA.ErpAlertPoster):
        raise TypeError("poster 는 ErpAlertPoster 여야 합니다")
    counts: Counter = Counter()
    stopped = None
    for row in store.due_deliveries(now, limit, kind):
        expires = Y._aware(row["expires_at"])
        if expires is None or now >= expires:
            store.record_delivery(row["recipient_id"], S.DELIVERY_FAILED, now, error_kind="expired")
            counts["expired"] += 1
            continue
        if stopped is not None:
            continue   # 키 거절·상한·연결 실패 — 이번 차례에는 더 부르지 않는다(다음 차례에 다시)
        try:
            title, lines = render(row["template"], row["source"], row["codes"], row["params"])
            payload = EA.build_payload(row["emp_idx"], row["severity"], title, lines, row["link_path"],
                                       row["dedupe_key"])
        except (RenderError, EA.AlertRejected):
            store.record_delivery(row["recipient_id"], S.DELIVERY_FAILED, now, error_kind="render")
            counts["failed"] += 1
            continue
        try:
            res = poster.send_alert(payload)
        except EA.AlertSendError as e:
            code = e.code if S.ERROR_CODE.fullmatch(e.code) else "other"
            if e.status == 400:
                store.record_delivery(row["recipient_id"], S.DELIVERY_FAILED, now, error_kind=code)
                counts["failed"] += 1
            else:
                counts[_retry_or_fail(store, row, now, code)] += 1
            if e.status != 400:
                stopped = code
            continue
        status = _REASON_STATUS[res.reason]
        store.record_delivery(row["recipient_id"], status, now, message_idx=res.message_idx if res.delivered else None)
        counts[status] += 1
        if res.reason == EA.REASON_TOTAL_CAP:
            stopped = "cap_total"
    return DispatchOutcome(dict(counts), stopped)


# ── 「오늘 끝」 심박(대표 결정 A3) ────────────────────────────────────
def note_morning_gap(store: S.Store, now: datetime) -> Optional[int]:
    """아침 요약을 만든 뒤에도 오늘 끝난 점검 회차가 없고(멈춤 · 죽음 · 시작 못 함) 아침 점검·점검 준비가 알린 것도
    없으면 대표에게 긴급 경보 한 번 — 점검이 없는 날 심박이 「정상」으로 나가 ① 08:10 감시까지 조용해지지 않게
    (검토 heartbeat-ok-without-finished-morning)."""
    _need_time(now)
    today = _local(now).date()
    if not _made(store, today, S.ALERT_DIGEST):
        return None
    if any(r["status"] == S.RUN_DONE for r in store.runs_on(today)):
        return None
    if any(a["source"] in ("morning", "readiness") for a in store.alerts_on(today, S.ALERT_SYSTEM)):
        return None
    return record_system_alert(store, now, "morning", [CODE_MORNING_NOT_DONE])


def _system_alerts_delivered(store: S.Store, today: date) -> bool:
    """오늘 시스템 경보가 모두 ① 에 들어갔나(넣음 · 같은 열쇠) — 아직 못 보냈거나 못 넣은 것이 하나라도 있으면 False."""
    for a in store.alerts_on(today, S.ALERT_SYSTEM):
        for r in store.alert_recipients(a["alert_id"]):
            if r["status"] not in (S.DELIVERY_SENT, S.DELIVERY_DUPLICATE):
                return False
    return True


def heartbeat_due(store: S.Store, now: datetime) -> bool:
    """오늘 아침 요약을 만들었고 · 오늘 시스템 경보가 모두 대표에게 들어갔고 · 오늘 심박을 아직 못 보냈고 · 마지막 시도 뒤
    2분이 지났을 때. 대표 경보가 들어가지 않은 날은 심박을 보내지 않는다 — ① 08:10 감시가 대신 대표에게 알린다
    (「trouble」은 「대표에게 이미 알렸다」는 뜻이라 알리지 못했으면 보내면 안 된다 · 검토 trouble-heartbeat-masks)."""
    _need_time(now)
    local = _local(now)
    today = local.date()
    if not _made(store, today, S.ALERT_DIGEST):
        return False
    hb = store.heartbeat()
    if hb is not None and hb["day"] == today and hb["sent_at"] is not None:
        return False
    if not _system_alerts_delivered(store, today):
        return False
    if hb is None or hb["day"] != today:
        return True
    return now - hb["last_try_at"] >= HEARTBEAT_RETRY


def heartbeat_status(store: S.Store, today: date) -> str:
    """오늘 시스템 경보가 있었으면 trouble(대표에게는 이미 알렸다 — ``heartbeat_due`` 가 들어간 뒤에만 부른다) · 없으면 ok."""
    return EA.HEARTBEAT_TROUBLE if store.alerts_on(today, S.ALERT_SYSTEM) else EA.HEARTBEAT_OK


def send_heartbeat(store: S.Store, now: datetime, poster: EA.ErpAlertPoster) -> HeartbeatOutcome:
    _need_time(now)
    if not isinstance(poster, EA.ErpAlertPoster):
        raise TypeError("poster 는 ErpAlertPoster 여야 합니다")
    today = _local(now).date()
    status = heartbeat_status(store, today)
    try:
        poster.send_heartbeat(today, status)
    except EA.AlertSendError as e:
        code = e.code if S.ERROR_CODE.fullmatch(e.code) else "other"
        store.record_heartbeat(today, status, now, sent=False, error_kind=code)
        return HeartbeatOutcome(False, status, code)
    store.record_heartbeat(today, status, now, sent=True)
    return HeartbeatOutcome(True, status)


def run_alerts(store: S.Store, now: datetime, poster: EA.ErpAlertPoster,
               policy: AlertPolicy = SHADOW) -> Tuple[ComposeOutcome, DispatchOutcome, Optional[HeartbeatOutcome]]:
    """스케줄러가 1분마다 부르는 한 차례 — 만들 것 만들기 → 점검 없는 날 경보 → 시스템 경보 보내기 → 심박(때가 되면)
    → 나머지 보내기. 요약이 수십 통이어도 심박이 그 뒤에 줄 서지 않는다(검토 heartbeat-queued)."""
    made = compose(store, now, policy)
    note_morning_gap(store, now)
    first = dispatch(store, now, poster, kind=S.ALERT_SYSTEM)
    hb = send_heartbeat(store, now, poster) if heartbeat_due(store, now) else None
    rest = dispatch(store, now, poster) if first.stopped is None else DispatchOutcome()
    counts = Counter(first.counts)
    counts.update(rest.counts)
    return made, DispatchOutcome(dict(counts), first.stopped or rest.stopped), hb
