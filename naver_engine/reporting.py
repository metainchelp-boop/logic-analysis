"""저장 원천을 집계하는 순수 보고서 모듈. 수집·저장·게시·AI 호출을 하지 않는다.

``period``의 anchor는 생성일이 아니라 보고할 기간 안의 실적일이다.
주간은 월~일 → 다음 월요일 10시, 월간은 1일~말일 → 다음 달 3일 10시(KST).
"""
from dataclasses import dataclass
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math


KST = timezone(timedelta(hours=9))
MAX_NUMBER = 9007199254740991
BASIC_FIELDS = ("imp", "clk", "spend")
CONVERSION_FIELDS = ("conversions", "conversion_value")
OUTPUT_FIELDS = {"imp": "impressions", "clk": "clicks", "spend": "spend",
                 "conversions": "conversions", "conversion_value": "conversion_value"}


class ReportInvalid(ValueError):
    """오류 문구에는 원천 번호·이름·금액을 넣지 않는다."""


@dataclass(frozen=True)
class ReportPeriod:
    kind: str
    start: date
    end: date
    due_at: datetime

    @property
    def key(self):
        return f"{self.kind}:{self.start.isoformat()}:{self.end.isoformat()}"

    def as_dict(self):
        return {"kind": self.kind, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "due_at": self.due_at.isoformat(), "days": (self.end-self.start).days+1,
                "timezone": "Asia/Seoul"}


def period(kind, anchor_date):
    """anchor_date가 속한 보고 기간. 오늘을 주면 아직 닫히지 않은 기간일 수 있다."""
    if type(anchor_date) is not date or kind not in ("weekly", "monthly"):
        raise ReportInvalid("보고서 종류 또는 날짜가 올바르지 않습니다")
    if kind == "weekly":
        start = anchor_date - timedelta(days=anchor_date.weekday())
        end = start + timedelta(days=6)
        due = end + timedelta(days=1)
    else:
        start = anchor_date.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        end, due = next_month-timedelta(days=1), next_month+timedelta(days=2)
    return ReportPeriod(kind, start, end, datetime.combine(due, time(10), tzinfo=KST))


def _now(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReportInvalid("시간대가 있는 시각이 필요합니다")
    return value.astimezone(KST)


def due_periods(now, since, *, limit=24):
    """since가 속한 기간부터 기한이 지난 기간을 오래된 순서로 최대 limit개 반환.

    실행 요일이 달라도 누락 회차를 찾는다. 호출자는 저장된 key로 중복을 막고,
    다음 묶음을 요청할 때 미처리 기간의 날짜로 since를 전진시킨다.
    기간 생성 자체도 종류마다 limit번까지만 수행해 긴 중단 기간을 제한한다.
    """
    now = _now(now)
    if type(since) is not date or type(limit) is not int or not 1 <= limit <= 120:
        raise ReportInvalid("시작 날짜 또는 처리 한도가 올바르지 않습니다")
    result = []
    for kind in ("weekly", "monthly"):
        current = period(kind, since)
        for _ in range(limit):
            if current.due_at > now:
                break
            result.append(current)
            current = period(kind, current.end+timedelta(days=1))
    return tuple(sorted(result, key=lambda p: (p.due_at, p.key))[:limit])


def _number(value):
    return type(value) in (int, float) and 0 <= value <= MAX_NUMBER and math.isfinite(value)


def _sum(values):
    result = sum((Decimal(str(value)) for value in values), Decimal(0))
    if result > MAX_NUMBER:
        raise ReportInvalid("지표 합계가 허용 범위를 넘었습니다")
    return int(result) if result == int(result) else float(result)


def _ratio(numerator, denominator, multiplier=1):
    if numerator is None or not denominator:
        return None
    result = numerator / denominator * multiplier
    return result if _number(result) else None


def _collected(row, day, now):
    try:
        raw = row.get("checked_at")
        at = _now(datetime.fromisoformat(raw) if isinstance(raw, str) else raw)
        if at > now or at.date() <= date.fromisoformat(day):
            return None
        source = row.get("source_at")
        if source is not None:
            source = _now(datetime.fromisoformat(source) if isinstance(source, str) else source)
            if source > at or source.date() <= date.fromisoformat(day):
                return None
        return at.isoformat()
    except (TypeError, ValueError):
        return None


def _rows_by_day(daily_rows, expected, report_period):
    rows = {}
    try:
        iterator = iter(daily_rows)
    except TypeError:
        raise ReportInvalid("일별 원천 목록이 아닙니다") from None
    for row in iterator:
        if not isinstance(row, Mapping):
            raise ReportInvalid("일별 원천 모양이 올바르지 않습니다")
        cid = row.get("customer_id")
        if type(cid) is not int or cid not in expected:
            continue  # 귀속·권한 밖 원천은 값·시각·지문 어디에도 넣지 않는다.
        raw = row.get("day")
        try:
            day = date.fromisoformat(raw) if isinstance(raw, str) else raw
            if type(day) is not date:
                raise ValueError()
        except (TypeError, ValueError):
            raise ReportInvalid("실적일 모양이 올바르지 않습니다") from None
        if not report_period.start <= day <= report_period.end:
            continue
        key = cid, day.isoformat()
        if key in rows:
            raise ReportInvalid("한 계정의 같은 실적일이 중복되었습니다")
        rows[key] = row
    return rows


def _fingerprint(report_period, expected, rows, now, review_required):
    # 다시 확인한 시각만 바뀌면 새 정정본이 아니다. 날짜별 값·완결 증거 변화는 총합이 같아도 반영한다.
    normalized = []
    for (cid, day), row in sorted(rows.items()):
        normalized.append([cid, day, _collected(row, day, now) is not None,
                           row.get("basic_complete") is True, row.get("conversion_complete") is True,
                           *[_sum([row[key]]) if _number(row.get(key)) else None for key in OUTPUT_FIELDS]])
    source = [1, report_period.key, expected, normalized, review_required]
    return hashlib.sha256(json.dumps(source, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _day_fingerprints(rows):
    """판 비교용 내부 지문. 계정 번호·원천 값은 공개 payload에 싣지 않는다."""
    days = {}
    for (cid, day), row in sorted(rows.items()):
        item = days.setdefault(day, {key: [] for key in OUTPUT_FIELDS})
        for key in OUTPUT_FIELDS:
            complete = row.get("basic_complete" if key in BASIC_FIELDS else "conversion_complete") is True
            item[key].append([cid, complete, row.get(key) if _number(row.get(key)) else None])
    return {day: {OUTPUT_FIELDS[key]: hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()
                  for key, value in item.items()} for day, item in days.items()}


def revision_metadata(previous, current, previous_report_id=None):
    """합계가 같은 실적일 이동도 정정으로 설명하며 값 역행/0을 허용한다."""
    old_days = previous.get("_day_fingerprints", {}) if previous is not None else {}
    new_days = current.get("_day_fingerprints", {})
    changed_days = sorted(day for day in set(old_days) | set(new_days)
                          if old_days.get(day) != new_days.get(day))
    old_totals = previous.get("totals", {}) if previous is not None else {}
    totals = current["totals"]
    changed_metrics = [key for key in totals if old_totals.get(key) != totals[key] or any(
        old_days.get(day, {}).get(key) != new_days.get(day, {}).get(key) for day in changed_days)]
    return {"previous_report_id": previous_report_id, "changed_metrics": changed_metrics,
            "metric_deltas": {key: totals[key]-old_totals[key] if previous is not None and
                              totals[key] is not None and old_totals.get(key) is not None else None for key in totals},
            "changed_days": changed_days,
            "completeness_changed": previous is not None and (previous.get("missing") != current["missing"] or
                                                              previous.get("ready") != current["ready"])}


def aggregate(report_period, expected_customers, daily_rows, now, *, has_open_issues=False):
    """호출자가 역사적 귀속을 확인한 계정 분모와 실적일별 계정 합계를 받는다.

    daily_rows: customer_id, day(실적일), basic_complete, conversion_complete,
    imp, clk, spend, conversions, conversion_value, checked_at, source_at(선택).
    완결 플래그는 저장소가 전체 캠페인·날짜·지표 증거를 검증한 경우만 설정한다.
    현재 관리 단계는 읽지 않는다. 과거의 확정 실적을 현재 환불/만료로 빼지 않는다.
    이 결과는 게시 권한이 아니다. 계정 확정·현재 담당 권한·비용 공개 검사는 호출자 몫이다.
    """
    now = _now(now)
    if not isinstance(report_period, ReportPeriod) or period(report_period.kind, report_period.start) != report_period:
        raise ReportInvalid("닫힌 보고 기간 모양이 올바르지 않습니다")
    try:
        expected = tuple(expected_customers)
    except TypeError:
        raise ReportInvalid("확정된 계정 목록이 아닙니다") from None
    if any(type(cid) is not int or cid <= 0 for cid in expected) or len(set(expected)) != len(expected):
        raise ReportInvalid("계정 목록이 올바르지 않거나 중복되었습니다")
    if type(has_open_issues) is not bool:
        raise ReportInvalid("열린 이슈 여부가 올바르지 않습니다")
    expected = tuple(sorted(expected))
    days = (report_period.end-report_period.start).days+1
    rows = _rows_by_day(daily_rows, set(expected), report_period)
    basic, conversion, roas, missing, times = [], [], [], [], []
    for account_index, cid in enumerate(expected, 1):
        for offset in range(days):
            day = (report_period.start+timedelta(days=offset)).isoformat()
            row = rows.get((cid, day))
            if row is None:
                missing.append({"account_index": account_index, "day": day, "reason": "day_missing",
                                "metrics": list(OUTPUT_FIELDS)})
                continue
            at = _collected(row, day, now)
            if at is None:
                missing.append({"account_index": account_index, "day": day, "reason": "source_unverified",
                                "metrics": list(OUTPUT_FIELDS)})
                continue
            times.append(at)
            basic_missing = [key for key in BASIC_FIELDS if row.get("basic_complete") is not True
                             or not _number(row.get(key))]
            conversion_missing = [key for key in CONVERSION_FIELDS if row.get("conversion_complete") is not True
                                  or not _number(row.get(key))]
            basic_ok, conversion_ok = not basic_missing, not conversion_missing
            if basic_ok:
                basic.append(row)
            if conversion_ok:
                conversion.append(row)
            if basic_ok and conversion_ok:
                roas.append(row)
            if not (basic_ok and conversion_ok):
                missing.append({"account_index": account_index, "day": day, "reason": "metrics_incomplete",
                                "metrics": basic_missing+conversion_missing})
    totals = {OUTPUT_FIELDS[key]: _sum(row[key] for row in basic) if basic else None for key in BASIC_FIELDS}
    totals.update({key: _sum(row[key] for row in conversion) if conversion else None for key in CONVERSION_FIELDS})
    roas_spend = _sum(row["spend"] for row in roas) if roas else None
    roas_value = _sum(row["conversion_value"] for row in roas) if roas else None
    blocked = ([] if expected else ["no_confirmed_accounts"])+([] if now >= report_period.due_at else ["not_due"])
    ready = not blocked and not missing
    review_required = report_period.kind == "monthly" or has_open_issues
    return {"period": report_period.as_dict(), "period_key": report_period.key,
            "generated_at": now.isoformat(), "status": "ready" if ready else "partial" if basic or conversion else "collecting",
            "ready": ready, "review_status": "needs_staff_review" if review_required
            else "not_required", "missing": missing, "blocked_reasons": blocked,
            "revision_fingerprint": _fingerprint(report_period, expected, rows, now, review_required),
            "_day_fingerprints": _day_fingerprints(rows),
            "coverage": {"accounts": len(expected), "expected_account_days": len(expected)*days,
                         "basic_complete_account_days": len(basic),
                         "conversion_complete_account_days": len(conversion),
                         "basic_complete": bool(expected) and len(basic) == len(expected)*days,
                         "conversion_complete": bool(expected) and len(conversion) == len(expected)*days,
                         "oldest_collected_at": min(times) if times else None,
                         "newest_collected_at": max(times) if times else None}, "totals": totals,
            "ratios": {"ctr": _ratio(totals["clicks"], totals["impressions"], 100),
                       "cpc": _ratio(totals["spend"], totals["clicks"]),
                       "roas": _ratio(roas_value, roas_spend, 100), "roas_account_days": len(roas),
                       "roas_spend": roas_spend, "roas_conversion_value": roas_value}}
