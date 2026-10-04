"""실관리 수집 주기와 실적 기간. 저장·계정 접근·전산 귀속 변경은 하지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone


DAILY_STAGES = frozenset({"진행중", "사후관리", "전략관리", "재계약진행중"})
KST = timezone(timedelta(hours=9))
COLLECTION_START = time(0, 1)


def generation_for(cycle: date) -> str:
    return datetime.combine(cycle, COLLECTION_START, tzinfo=KST).isoformat()


def revalidation_periods(when: date | datetime, *, managed: bool, prior_managed: bool = False):
    """새 자동 회차만 반환한다. 진행 중 회차의 고정 기간은 저장소가 보존한다."""
    day = _kst_day(when)
    end = day-timedelta(days=1)
    result = []
    if managed and day.day >= 3:
        month_end = day.replace(day=1)-timedelta(days=1)
        result.append(("report_monthly", day.replace(day=3), month_end.replace(day=1), month_end))
    if managed:
        monday = day-timedelta(days=day.weekday())
        result.append(("report_weekly", monday, monday-timedelta(days=7), monday-timedelta(days=1)))
    if day.weekday() == 6 and (managed or prior_managed):
        result.append(("reconcile", day, end-timedelta(days=30), end))
    if managed:
        result.append(("recent", day, end-timedelta(days=2), end))
    return result


@dataclass(frozen=True)
class CollectionDecision:
    cadence: str
    reason: str
    attributable: bool


@dataclass(frozen=True)
class CollectionPeriod:
    cycle_day: date
    since: date
    until: date


def classify(*, stage: str | None, stage_revision: str | None, matched: bool,
             authority_valid: bool, source_current: bool,
             excluded_revision: str | None = None, included_revision: str | None = None) -> CollectionDecision:
    """현재 확인된 사실로 판정한다. 후보 선정과 호출 직전에 같은 판정을 쓴다.

    미확인/숨김 단계는 None으로, 확인된 기타 단계는 원문으로 전달한다.
    revision은 동일 단계의 반복 동기화에서는 유지하고 단계 변경 때 바꾼다.
    이 판정은 접근 권한을 발급하거나 과거 실적의 ERP 귀속을 확정하지 않는다.
    """
    if any(type(value) is not bool for value in (matched, authority_valid, source_current)):
        raise ValueError("매칭·대행 권한·원천 최신 여부는 참/거짓이어야 합니다")
    if stage is not None and not isinstance(stage, str):
        raise ValueError("단계는 글자 또는 미확인이어야 합니다")
    for revision in (stage_revision, excluded_revision, included_revision):
        if revision is not None and (not isinstance(revision, str) or not revision.strip()):
            raise ValueError("단계 개정값은 빈칸이 아닌 글자 또는 미확인이어야 합니다")
    if not authority_valid:
        return CollectionDecision("blocked", "AUTHORITY_INVALID", False)
    if not source_current:
        return CollectionDecision("blocked", "SOURCE_STALE", False)
    if not matched:
        return CollectionDecision("weekly", "UNMATCHED_ACCOUNT", False)
    key = "".join(stage.split()) if isinstance(stage, str) else ""
    if not key:
        return CollectionDecision("weekly", "UNKNOWN_STAGE", False)
    if not stage_revision:
        return CollectionDecision("blocked", "UNKNOWN_STAGE", False)
    # 과거 수동 포함·제외는 감사 이력으로만 남긴다. 관제 자동 수집 주기는
    # 사람이 바꾸지 않으며 현재 실관리 4단계/그 밖의 단계로만 결정한다.
    if key in DAILY_STAGES:
        return CollectionDecision("daily", "MANAGED_STAGE", True)
    return CollectionDecision("weekly", "NONMANAGED_STAGE", True)


def period_for(cadence: str, when: date | datetime) -> CollectionPeriod:
    """일자는 한국 날짜로, 시각은 한국시간으로 바꿔 완료된 실적 기간을 구한다."""
    if cadence not in ("daily", "weekly"):
        raise ValueError("수집 기간은 일일 또는 주간만 지원합니다")
    day = _kst_day(when)
    if cadence == "weekly":
        cycle_day = day - timedelta(days=(day.weekday() + 1) % 7)
        return CollectionPeriod(cycle_day, cycle_day - timedelta(days=7), cycle_day - timedelta(days=1))
    until = day - timedelta(days=1)
    return CollectionPeriod(day, until, until)


def is_due(decision: CollectionDecision, when: date | datetime, *, completed_cycle: date | None = None,
           started_cycle: date | None = None) -> bool:
    """자동 시작/계속 여부. 회차 안의 횟수 제한·지연은 저장소가 별도로 검사한다."""
    if decision.cadence == "blocked":
        return False
    day = _kst_day(when)
    period = period_for(decision.cadence, day)
    for cycle in (completed_cycle, started_cycle):
        if cycle is not None and (type(cycle) is not date or cycle > period.cycle_day
                                  or (decision.cadence == "weekly" and cycle.weekday() != 6)):
            raise ValueError("회차는 미래가 아닌 해당 주기의 시작 날짜여야 합니다")
    if completed_cycle == period.cycle_day:
        return False
    return decision.cadence == "daily" or day.weekday() == 6 or started_cycle == period.cycle_day


def _kst_day(when: date | datetime) -> date:
    if isinstance(when, datetime):
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("시간대가 있는 시각이어야 합니다")
        return when.astimezone(KST).date()
    if type(when) is not date:
        raise ValueError("한국 날짜 또는 시간대가 있는 시각이어야 합니다")
    return when
