"""아침 점검 규칙 — 계정 한 곳의 읽은 자료로 「발견」 목록을 낸다 (설계 v1.7 점검 표 · v1.8 반박 C1 · 0단계 실측).

순수 함수 — 네트워크·저장·시계를 모른다. 엔진(S9)이 읽기 관문 결과를 아래 입력 모양으로 바꿔 넣는다.

지키는 것:
- **규칙마다 「돌림 / 못 돌림(사유)」을 돌려준다**(반박 C1). 이슈는 그 규칙이 오늘 온전한 자료로 돌았을 때만 저절로 풀린다(S9).
- **모르는 값은 0 이 아니다.** 입력의 ``None`` = 모름 → 그 값을 쓰는 규칙은 돌리지 않는다(못 돌림 · 사유).
- **자료 늦음**(네이버 어제 자료가 덜 들어옴)이면 ④ 안 나감 · ⑤ 급변 · ⑥ 단계와 광고비는 돌리지 않는다.
  ② 키 거절 · ③ 비즈머니 · ⑦ 기간 끝남은 돈다(③ 의 평균은 엔진이 온전한 날로만 계산해 넣는다).
- 계정 상태(``status``)는 판정 함수(verdict)의 ``CHECK_*`` 값 그대로다.

규칙 번호(설계 v1.7 표 순서):
  ② key_rejected   캠페인 목록을 네이버가 거절(401·403·1006·1018) → 계정 ⚪ + 🟡
  ③ bizmoney       잔액 ÷ 하루 평균 광고비 — 1일 미만 🔴 · 3일 미만 🟡 · 평균 0 · 켜진 캠페인 있음 · 잔액 0 이하 → 🟡
                   (잠금 두 칸은 뜻을 확인하기 전까지 기본 꺼짐 — 반박 M13)
  ④ no_delivery    켜진 캠페인이 어제 노출 0 인데 최근 7일에는 노출이 있었다 → 전부면 🔴 · 일부면 🟡
  ⑤ spend_jump     어제 광고비가 같은 요일 4주 평균의 2배 이상 · 절반 이하 → 🟡 (기준·어제 둘 다 1만원 미만이면 보지 않음)
  ⑥ stage_spend    환불중·계약 만료인데 어제 광고비 > 0 → 🟡 · 진행중인데 최근 3일 광고비 0 → 🟡
  ⑦ period_end     캠페인 기간이 3일 안에 끝남 → ⓘ
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence, Tuple

from .thresholds import DEFAULTS, Thresholds
from .verdict import (CHECK_DATA_LATE, CHECK_KEY_REJECTED, CHECK_OK, CHECK_PARTIAL, CHECK_SYSTEM_GAP, SEV_INFO,
                      SEV_RED, SEV_YELLOW)

KST = timezone(timedelta(hours=9))

R_KEY = "key_rejected"
R_BIZMONEY = "bizmoney"
R_BIZMONEY_LOCK = "bizmoney_lock"
R_NO_DELIVERY = "no_delivery"
R_SPEND_JUMP = "spend_jump"
R_STAGE_SPEND = "stage_spend"
R_PERIOD_END = "period_end"
ALL_RULES = (R_KEY, R_BIZMONEY, R_BIZMONEY_LOCK, R_NO_DELIVERY, R_SPEND_JUMP, R_STAGE_SPEND, R_PERIOD_END)
LATE_SKIPPED = frozenset({R_NO_DELIVERY, R_SPEND_JUMP, R_STAGE_SPEND})
# 우리 쪽(시스템) 사유 — 광고주마다 「확인 필요」로 올리지 않고 대표 시스템 경보로 간다(계정은 ⚪ · 🟢 불가)
SYSTEM_REASONS = frozenset({"stage-stale", "stage-unknown"})

# 규칙 켜기 — 뜻을 확인하지 못한 것은 기본 꺼짐(반박 M13 · 날짜가 지나도 저절로 켜지지 않는다)
DEFAULT_SWITCHES = {r: True for r in ALL_RULES}
DEFAULT_SWITCHES[R_BIZMONEY_LOCK] = False

KIND_KEY_REJECTED = "KEY_REJECTED"  # 읽기 관문의 오류 종류 이름(naver_read.KIND_KEY_REJECTED 와 같은 글자)

STAGE_ENDED_SPEND = frozenset({"환불중", "계약만료"})   # 빈칸 뺀 글자
STAGE_RUNNING = frozenset({"진행중"})
_WS = re.compile(r"\s+")
ACTIVE_STATUS = "ELIGIBLE"
EXCLUDED_TYPES = frozenset({"BRAND_SEARCH"})             # 브랜드검색은 정액 계약이라 노출 0 판정에서 뺀다


@dataclass(frozen=True)
class CampaignInfo:
    campaign_id: str
    tp: str
    status: str
    user_lock: bool
    del_flag: bool = False
    use_period: bool = False
    period_end: Optional[str] = None      # 네이버 원문(UTC 시각 글자)
    shared_budget_lock: bool = False
    yday_imp: Optional[int] = None        # 어제 노출 · None = 모름
    week_imp: Optional[int] = None        # 최근 7일(D-7~D-1) 노출 합계 · None = 모름


@dataclass(frozen=True)
class AccountInput:
    customer_id: int
    campaigns: Optional[Tuple[CampaignInfo, ...]]   # None = 못 읽음
    campaigns_error: Optional[str] = None           # 못 읽은 까닭(읽기 관문 오류 종류)
    bizmoney: Optional[float] = None
    budget_lock: Optional[bool] = None
    refund_lock: Optional[bool] = None
    bizmoney_error: Optional[str] = None
    avg_daily_spend: Optional[float] = None         # 온전한 7일로만 계산 · 아니면 None
    yday_spend: Optional[float] = None
    recent_spend: Optional[Tuple[Optional[float], ...]] = None      # 최근 N일(오래된 날 먼저)
    same_weekday_spend: Optional[Tuple[Optional[float], ...]] = None  # 같은 요일 1~4주 전
    stats_error: Optional[str] = None
    data_late: bool = False


@dataclass(frozen=True)
class StageInfo:
    stage: str
    as_of: datetime


@dataclass(frozen=True)
class Finding:
    rule: str
    code: str
    target: str            # 이슈 열쇠의 대상 — 계정이면 "acc:<번호>" · 캠페인이면 캠페인 번호
    level: str             # red · yellow · info
    facts: Tuple[Tuple[str, object], ...] = ()


@dataclass(frozen=True)
class CheckReport:
    status: str
    findings: Tuple[Finding, ...]
    rules_run: Tuple[str, ...]
    rules_not_run: Tuple[Tuple[str, str], ...]   # (규칙, 사유)

    def ran(self, rule: str) -> bool:
        return rule in self.rules_run


def _stage_key(stage: Optional[str]) -> str:
    return _WS.sub("", stage) if isinstance(stage, str) else ""


def _period_end_kst(raw: Optional[str]) -> Optional[date]:
    """네이버 기간 끝 글자(UTC) → 한국 날짜. 못 읽으면 None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).date()


def _active(c: CampaignInfo) -> bool:
    return (c.status == ACTIVE_STATUS and not c.user_lock and not c.del_flag and c.tp not in EXCLUDED_TYPES)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


def _num_ok(v) -> bool:
    return _is_num(v) and v >= 0


def run_checks(account: AccountInput, stage: Optional[StageInfo], now: datetime,
               th: Thresholds = DEFAULTS, switches: Optional[Mapping[str, bool]] = None) -> CheckReport:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 한다")
    sw = dict(DEFAULT_SWITCHES)
    if switches:
        unknown = set(switches) - set(ALL_RULES)
        if unknown:
            raise ValueError("모르는 규칙 스위치")
        sw.update({k: bool(v) for k, v in switches.items()})
    today = now.astimezone(KST).date()
    acc_target = f"acc:{account.customer_id}"
    findings = []
    ran = []
    not_run = []

    def skip(rule, reason):
        not_run.append((rule, reason))

    def off(rule):
        return not sw.get(rule, False)

    # ② 키 거절 — 캠페인 목록을 못 읽으면 나머지는 돌릴 수 없다
    if account.campaigns is None:
        if account.campaigns_error == KIND_KEY_REJECTED:
            ran.append(R_KEY)
            findings.append(Finding(R_KEY, "key_rejected", acc_target, SEV_YELLOW))
            status = CHECK_KEY_REJECTED
        else:
            skip(R_KEY, "campaigns-unread")
            status = CHECK_PARTIAL
        for r in ALL_RULES[1:]:
            if not off(r):
                skip(r, "campaigns-unread")
        return CheckReport(status, tuple(findings), tuple(ran), tuple(not_run))
    ran.append(R_KEY)
    campaigns = account.campaigns
    active = [c for c in campaigns if _active(c)]

    # ③ 비즈머니
    if off(R_BIZMONEY):
        pass
    elif not _is_num(account.bizmoney):
        skip(R_BIZMONEY, "bizmoney-unread")
    elif account.avg_daily_spend is None or not _num_ok(account.avg_daily_spend):
        skip(R_BIZMONEY, "avg-incomplete")      # 7일이 다 있을 때만 평균을 쓴다(반박 C1(d))
    else:
        ran.append(R_BIZMONEY)
        bal, avg = float(account.bizmoney), float(account.avg_daily_spend)
        if avg > 0:
            days = bal / avg
            level = SEV_RED if days < th.bizmoney_red_days else SEV_YELLOW if days < th.bizmoney_yellow_days else None
            if level:
                findings.append(Finding(R_BIZMONEY, "bizmoney_low", acc_target, level,
                                        (("days_left", round(days, 2)),)))
        elif active and bal <= 0:
            findings.append(Finding(R_BIZMONEY, "bizmoney_empty", acc_target, SEV_YELLOW))
    if not off(R_BIZMONEY_LOCK):
        if not isinstance(account.budget_lock, bool) or not isinstance(account.refund_lock, bool):
            skip(R_BIZMONEY_LOCK, "lock-unread")
        else:
            ran.append(R_BIZMONEY_LOCK)
            if account.budget_lock:
                findings.append(Finding(R_BIZMONEY_LOCK, "budget_lock", acc_target, SEV_RED))
            if account.refund_lock:
                findings.append(Finding(R_BIZMONEY_LOCK, "refund_lock", acc_target, SEV_YELLOW))

    # ⑦ 기간 곧 끝남(캠페인마다)
    if not off(R_PERIOD_END):
        unreadable = [c for c in active if c.use_period and _period_end_kst(c.period_end) is None]
        if unreadable:
            skip(R_PERIOD_END, "period-unreadable")
        else:
            ran.append(R_PERIOD_END)
            for c in active:
                if not c.use_period:
                    continue
                left = (_period_end_kst(c.period_end) - today).days
                if 0 <= left <= th.period_end_days:
                    findings.append(Finding(R_PERIOD_END, "period_ending", c.campaign_id, SEV_INFO,
                                            (("days_left", left),)))

    # 자료 늦음이면 ④⑤⑥ 은 돌리지 않는다
    if account.data_late:
        for r in (R_NO_DELIVERY, R_SPEND_JUMP, R_STAGE_SPEND):
            if not off(r):
                skip(r, "data-late")
    else:
        # ④ 켜져 있는데 안 나감
        if not off(R_NO_DELIVERY):
            if any(c.yday_imp is None or c.week_imp is None for c in active):
                skip(R_NO_DELIVERY, "impressions-unknown")
            else:
                ran.append(R_NO_DELIVERY)
                had = [c for c in active if c.week_imp > 0]
                stopped = [c for c in had if c.yday_imp == 0]
                if stopped:
                    hints = []
                    if any(c.shared_budget_lock for c in stopped):
                        hints.append("shared-budget-lock")
                    if any(f.code in ("bizmoney_low", "bizmoney_empty") for f in findings):
                        hints.append("bizmoney")
                    level = SEV_RED if len(stopped) == len(had) else SEV_YELLOW
                    findings.append(Finding(R_NO_DELIVERY, "active_no_impressions", acc_target, level,
                                            (("stopped", len(stopped)), ("had_impressions", len(had)),
                                             ("hints", tuple(hints)))))
        # ⑤ 광고비 급변
        if not off(R_SPEND_JUMP):
            base = [v for v in (account.same_weekday_spend or ()) if _num_ok(v)]
            if not _num_ok(account.yday_spend):
                skip(R_SPEND_JUMP, "yesterday-unknown")
            elif len(base) < th.jump_min_weeks:
                skip(R_SPEND_JUMP, "baseline-insufficient")
            else:
                ran.append(R_SPEND_JUMP)
                b = sum(base) / len(base)
                y = float(account.yday_spend)
                if not (b < th.jump_min_spend and y < th.jump_min_spend):   # 둘 다 작을 때만 보지 않는다
                    if (b == 0 and y > 0) or (b > 0 and y >= b * th.jump_up_ratio):
                        findings.append(Finding(R_SPEND_JUMP, "spend_up", acc_target, SEV_YELLOW,
                                                (("baseline", round(b)), ("yesterday", round(y)))))
                    elif b > 0 and y <= b * th.jump_down_ratio:
                        findings.append(Finding(R_SPEND_JUMP, "spend_down", acc_target, SEV_YELLOW,
                                                (("baseline", round(b)), ("yesterday", round(y)))))
        # ⑥ 계약 단계와 광고비
        if not off(R_STAGE_SPEND):
            key = _stage_key(stage.stage) if stage else ""
            if stage is None or not isinstance(stage.as_of, datetime) or stage.as_of.tzinfo is None:
                skip(R_STAGE_SPEND, "stage-unknown")
            elif now - stage.as_of > timedelta(hours=th.stage_stale_hours):
                skip(R_STAGE_SPEND, "stage-stale")
            elif key in STAGE_ENDED_SPEND:
                if not _num_ok(account.yday_spend):
                    skip(R_STAGE_SPEND, "yesterday-unknown")
                else:
                    ran.append(R_STAGE_SPEND)
                    if account.yday_spend > 0:
                        findings.append(Finding(R_STAGE_SPEND, "spend_after_contract", acc_target, SEV_YELLOW,
                                                (("stage", key), ("yesterday", round(account.yday_spend)))))
            elif key in STAGE_RUNNING:
                recent = account.recent_spend
                if not recent or len(recent) < th.zero_spend_days or \
                        not all(_num_ok(v) for v in recent[-th.zero_spend_days:]):
                    skip(R_STAGE_SPEND, "recent-unknown")
                else:
                    ran.append(R_STAGE_SPEND)
                    if sum(recent[-th.zero_spend_days:]) == 0:
                        findings.append(Finding(R_STAGE_SPEND, "running_zero_spend", acc_target, SEV_YELLOW,
                                                (("days", th.zero_spend_days),)))
            else:
                ran.append(R_STAGE_SPEND)   # 이 규칙이 볼 단계가 아니다 — 돌았고 발견 없음

    reasons = {reason for _r, reason in not_run}
    if reasons - SYSTEM_REASONS - {"data-late"}:
        status = CHECK_PARTIAL           # 읽어야 할 것을 못 읽음 — 확인 필요
    elif account.data_late:
        status = CHECK_DATA_LATE
    elif reasons & SYSTEM_REASONS:
        status = CHECK_SYSTEM_GAP
    else:
        status = CHECK_OK
    return CheckReport(status, tuple(findings), tuple(ran), tuple(not_run))
