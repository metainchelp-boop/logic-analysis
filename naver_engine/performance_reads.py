"""닫힌 실적일별 원천 수집. 캠페인별 GET만 쓰며 요약을 날짜에 나누지 않는다.

기본 지표·모든 날짜를 확인한 캠페인만 체크포인트에 더한다. 다음 회차는 그다음
캠페인부터 이어 간다. 전환 미제공/추적 미확인은 기본 자료 성공과 따로 보존한다.
저장소가 작업 귀속·단계·현재 위임을 매 요청 직전에 다시 검증한다.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
from time import monotonic

from . import handles as H, naver_read as N, store as S


FIELDS = ("impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt")
OUTPUTS = ("imp", "clk", "spend", "conversions", "conversion_value")
MAX_NUMBER = 9007199254740991


class CheckpointInvalid(ValueError):
    """값·계정·원문을 오류 문구에 넣지 않는다."""


class PerformanceIncomplete(ValueError):
    pass


class SourceAggregating(PerformanceIncomplete):
    """정상 원천 응답이 집계 지연임을 입증한 경우만 별도 대기한다."""


@dataclass(frozen=True)
class PerformanceOutcome:
    code: str
    counts: dict = field(default_factory=dict)


def _period(job):
    try:
        start = date.fromisoformat(job["period_start"])
        end = date.fromisoformat(job["period_end"])
        if not 0 <= (end-start).days < 31 or type(job["customer_id"]) is not int or job["customer_id"] <= 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise CheckpointInvalid("일별 원천 작업 기간 또는 계정이 올바르지 않습니다") from None
    return start, end


def _days(start, end):
    return tuple((start+timedelta(days=n)).isoformat() for n in range((end-start).days+1))


def _number(value, key):
    if value is None and key in FIELDS[3:]:
        return None
    if type(value) not in (int, float) or not 0 <= value <= MAX_NUMBER or not math.isfinite(value) \
            or (key != "convAmt" and int(value) != value):
        raise CheckpointInvalid("일별 원천 숫자가 완결되지 않았습니다")
    return int(value) if int(value) == value else value


def _add(left, right, key):
    if left is None or right is None:
        return None
    value = Decimal(str(left))+Decimal(str(right))
    if value > MAX_NUMBER:
        raise CheckpointInvalid("일별 원천 합계가 허용 범위를 넘었습니다")
    return _number(int(value) if value == int(value) else float(value), key)


def fingerprint(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def _cycle(raw, end, now=None):
    try:
        at = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None \
                or at.astimezone(S.KST).date() <= end or (now is not None and at > now):
            raise ValueError()
        return at.astimezone(S.KST)
    except (TypeError, ValueError):
        raise CheckpointInvalid("일별 자료 기준 시각이 완결되지 않았습니다") from None


def validate_progress(source, job):
    """저장소와 수집기가 함께 검사한다. {실적일: 원천지표+conversion_complete} 반환."""
    start, end = _period(job)
    required = {"customer_id", "period_start", "period_end", "campaign_ids", "fingerprint", "next_index",
                "cycles", "day_totals", "conversion_evidence"}
    if "generation" in job:
        required.add("generation")
    if not isinstance(source, dict) or set(source) != required or type(source["customer_id"]) is not int \
            or source["customer_id"] != job["customer_id"] or source["period_start"] != start.isoformat() \
            or source["period_end"] != end.isoformat() or source.get("generation") != job.get("generation"):
        raise CheckpointInvalid("일별 이어읽기 계정 또는 기간이 다릅니다")
    ids, index = source["campaign_ids"], source["next_index"]
    if not isinstance(ids, list) or any(not isinstance(i, str) or not N._CAMPAIGN_ID.fullmatch(i) for i in ids) \
            or ids != sorted(set(ids)) or source["fingerprint"] != fingerprint(ids):
        raise CheckpointInvalid("일별 캠페인 목록 지문이 다릅니다")
    if type(index) is not int or not 0 <= index <= len(ids) or not isinstance(source["cycles"], list) \
            or len(source["cycles"]) != index or type(source["conversion_evidence"]) is not bool \
            or (not ids and source["conversion_evidence"]):
        raise CheckpointInvalid("일별 이어읽기 위치 또는 근거가 다릅니다")
    for cycle in source["cycles"]:
        parsed = _cycle(cycle, end)
        if job.get("generation") and parsed.date() < datetime.fromisoformat(job["generation"]).astimezone(S.KST).date():
            raise CheckpointInvalid("재확인 세대보다 오래된 일별 원천입니다")
    totals = source["day_totals"]
    if not isinstance(totals, dict) or set(totals) != set(_days(start, end)):
        raise CheckpointInvalid("일별 이어읽기 날짜가 빠지거나 다릅니다")
    out = {}
    for day, row in totals.items():
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise CheckpointInvalid("일별 이어읽기 지표 모양이 다릅니다")
        out[day] = {key: _number(row[key], key) for key in FIELDS}
        if index == 0 and any(out[day][key] != (None if not ids and key in FIELDS[3:] else 0) for key in FIELDS):
            raise CheckpointInvalid("아직 읽지 않은 캠페인의 지표가 들어 있습니다")
        out[day]["conversion_complete"] = index == len(ids) and source["conversion_evidence"] \
            and all(out[day][key] is not None for key in FIELDS[3:])
    return out


def _campaign_ids(campaigns):
    ids = sorted(c["nccCampaignId"] for c in campaigns)
    if len(ids) != len(set(ids)) or any(not N._CAMPAIGN_ID.fullmatch(i) for i in ids):
        raise N.StatsShapeUnknown("일별 캠페인 목록이 겹치거나 다릅니다")
    return ids


def _read(reader, handle, job, values, store, clock):
    start, end = _period(job)
    if end >= clock().astimezone(S.KST).date():
        raise PerformanceIncomplete("아직 닫히지 않은 실적일입니다")
    progress = store.performance_progress(job)
    if progress is not None:
        validate_progress(progress, job)
        for raw in progress["cycles"]:
            _cycle(raw, end, clock())
    campaigns = reader.get_campaigns(handle)
    ids = _campaign_ids(campaigns)
    values["campaigns"] = campaigns
    values["bizmoney"] = reader.get_bizmoney(handle)["bizmoney"]
    values["bizmoney_at"] = clock().astimezone(S.KST).isoformat()
    reader.check_budget()
    if progress is None or progress["campaign_ids"] != ids:
        totals = {day: dict.fromkeys(FIELDS, 0) for day in _days(start, end)}
        if not ids:
            for row in totals.values():
                row.update(ccnt=None, convAmt=None)
        progress = dict(customer_id=job["customer_id"], period_start=start.isoformat(), period_end=end.isoformat(),
                        campaign_ids=ids, fingerprint=fingerprint(ids), next_index=0, cycles=[],
                        day_totals=totals, conversion_evidence=bool(ids))
        if "generation" in job:
            progress["generation"] = job["generation"]
        store.record_performance_progress(job, clock(), progress)
    while progress["next_index"] < len(ids):
        campaign_id = ids[progress["next_index"]]
        daily = reader.get_stats_daily(handle, campaign_id, start, end, fields=FIELDS)
        reader.check_budget()
        # HTTP/인증/모양/미래시각 오류는 집계 대기로 숨기지 않는다.
        try:
            for row in daily.days.values():
                if set(row) != set(FIELDS):
                    raise CheckpointInvalid("일별 통계 지표가 다릅니다")
                for key in FIELDS:
                    _number(row[key], key)
        except CheckpointInvalid:
            raise PerformanceIncomplete("일별 기본 지표가 완결되지 않았습니다") from None
        raw_cycle = daily.cycle_base_tm
        if isinstance(raw_cycle, datetime) and raw_cycle.tzinfo is not None and raw_cycle <= clock():
            generation_day = datetime.fromisoformat(job["generation"]).astimezone(S.KST).date() if job.get("generation") else None
            if not daily.data_fresh or daily.missing_days or (generation_day and raw_cycle.astimezone(S.KST).date() < generation_day):
                raise SourceAggregating("원천 일별 집계가 아직 완료되지 않았습니다")
        if not daily.data_fresh or daily.missing_days or set(daily.days) != set(_days(start, end)):
            raise PerformanceIncomplete("일별 통계 날짜가 완결되지 않았습니다")
        try:
            cycle = _cycle(daily.cycle_base_tm, end, clock())
        except CheckpointInvalid:
            raise PerformanceIncomplete("일별 자료 기준 시각을 확인하지 못했습니다") from None
        update = deepcopy(progress)
        evidence = job.get("conversion_tracking_confirmed") is True
        try:
            for day, row in daily.days.items():
                if set(row) != set(FIELDS):
                    raise CheckpointInvalid("일별 통계 지표가 다릅니다")
                normalized = {key: _number(row[key], key) for key in FIELDS}
                evidence = evidence or any(normalized[key] is not None and normalized[key] > 0 for key in FIELDS[3:])
                for key in FIELDS:
                    update["day_totals"][day][key] = _add(update["day_totals"][day][key], normalized[key], key)
        except CheckpointInvalid:
            raise PerformanceIncomplete("일별 기본 지표가 완결되지 않았습니다") from None
        update["conversion_evidence"] = progress["conversion_evidence"] and evidence
        update["cycles"].append(cycle.isoformat())
        update["next_index"] += 1
        store.record_performance_progress(job, clock(), update)
        progress = update
        values["progressed"] = True
    after = reader.get_campaigns(handle)
    reader.check_budget()
    if _campaign_ids(after) != ids:
        values.update(status="retry", error_code="CAMPAIGNS_CHANGED")
        return
    totals = validate_progress(progress, job)
    at = clock().astimezone(S.KST).isoformat()
    source_at = min(progress["cycles"]) if progress["cycles"] else at
    values.update(status="ok", campaigns=after, campaign_fingerprint=progress["fingerprint"], daily_rows=[
        {"customer_id": job["customer_id"], "day": day, "basic_complete": True,
         "conversion_complete": row["conversion_complete"], **dict(zip(OUTPUTS, (row[k] for k in FIELDS))),
         "checked_at": at, "source_at": source_at} for day, row in sorted(totals.items())])


def run_performance(reader, store, clock, *, limit=24, max_calls=24, max_seconds=30, per_account_calls=8):
    if type(limit) is not int or not 1 <= limit <= 24 or type(max_calls) is not int or not 1 <= max_calls <= 24 \
            or type(max_seconds) not in (int, float) or not 0 < max_seconds <= 30 \
            or type(per_account_calls) is not int or not 1 <= per_account_calls <= 8:
        raise ValueError("일별 성과 수집 예산이 올바르지 않습니다")
    if reader.rate_limited:
        return PerformanceOutcome("BUDGET")
    now, initial, started = clock(), reader.calls, monotonic()
    if store.inventory_snapshot(now) is None:
        return PerformanceOutcome("NOT_READY")
    today, counts = now.astimezone(S.KST).date(), Counter()
    jobs = store.performance_work(now, limit)
    supplement = [job for job in jobs if job["kind"] in (
        "backfill", "recent", "reconcile", "report_weekly", "report_monthly", "manual_period")
        or (job["kind"] == "daily" and job.get("cycle_day", str(today)) < str(today))]
    primary = [job for job in jobs if job not in supplement]
    # 18회 안의 최대 6회/비례 시간만 예약한다. 남은 기회는 최초 수집에 반환한다.
    reserve = min(6, max_calls-3) if supplement and primary and max_calls >= 6 else 0
    pending, seen, phase = list(primary), set(), "primary"
    phase_calls, phase_time = max_calls-reserve, max_seconds*(max_calls-reserve)/max_calls
    if not primary:
        pending, supplement, phase = supplement, [], "supplement_only"
    with reader.bounded_requests(max_calls=max_calls, max_seconds=max_seconds):
        while pending or supplement or (phase == "supplement" and primary):
            elapsed = max((clock()-now).total_seconds(), monotonic()-started)
            if phase == "primary" and (not pending or phase_calls-(reader.calls-initial) < 3 or elapsed >= phase_time):
                pending, primary, supplement, phase = supplement, pending, [], "supplement"
                phase_calls = min(max_calls, reader.calls-initial+6)
                phase_time = max_seconds
            if phase == "supplement" and (not pending or phase_calls-(reader.calls-initial) < 3):
                pending, phase, phase_calls = primary, "remaining", max_calls
            if not pending:
                break
            job = pending.pop(0)
            if job["customer_id"] in seen:
                continue
            if elapsed >= max_seconds or max_calls-(reader.calls-initial) < 3:
                return PerformanceOutcome("BUDGET", dict(counts))
            if clock() < now or clock().astimezone(S.KST).date() != today:
                return PerformanceOutcome("SOURCE_CHANGED", dict(counts))
            values = {}
            try:
                seen.add(job["customer_id"])
                store.begin_performance_check(job, clock())
                handle = H.issue_inventory_handle(customer_id=job["customer_id"], snapshot_at=job["snapshot_at"], now=clock(),
                    validate=lambda cid, snapshot, at: store.performance_account_valid(job, at))
                with reader.bounded_requests(max_calls=min(per_account_calls, phase_calls-(reader.calls-initial)),
                        max_seconds=min(10, max_seconds-elapsed, phase_time-elapsed)):
                    _read(reader, handle, job, values, store, clock)
                    reader.check_budget()
            except N.NaverApiError as exc:
                values.update(status="reauth_required" if exc.kind == N.KIND_KEY_REJECTED else "retry", error_code=exc.kind)
            except SourceAggregating:
                values.update(status="source_wait", error_code="SOURCE_AGGREGATING")
            except (N.StatsShapeUnknown, PerformanceIncomplete):
                values.update(status="retry", error_code="STATS_INCOMPLETE")
            except CheckpointInvalid:
                values.update(status="limited", error_code="CHECKPOINT_INVALID")
            except N.RunAbort:
                values.update(status="partial" if values.get("progressed") else "retry", error_code="REQUEST_BUDGET")
            except (H.NotEligible, H.HandleInvalid, S.StoreRefused):
                return PerformanceOutcome("SOURCE_CHANGED", dict(counts))
            except S.StoreError:
                raise
            except Exception:
                values.update(status="retry", error_code="UNEXPECTED")
            try:
                status = store.record_performance_check(job, clock(), values)
            except S.StoreRefused:
                return PerformanceOutcome("SOURCE_CHANGED", dict(counts))
            counts[status] += 1
            if reader.rate_limited:
                return PerformanceOutcome("BUDGET", dict(counts))
    return PerformanceOutcome("DONE", dict(counts))
