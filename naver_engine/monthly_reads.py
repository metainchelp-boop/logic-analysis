"""월초~어제 원천. 전일 수집 뒤 남은 회차 예산만 사용하며 ERP로 보내지 않는다."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from time import monotonic

from . import handles as H, naver_read as N, store as S

FIELDS = ("impCnt", "clkCnt", "salesAmt", "convAmt")
OUTPUTS = ("imp", "clk", "spend", "conversion_value")
MAX_NUMBER = 9007199254740991


class CheckpointInvalid(ValueError):
    pass


class MonthlyIncomplete(ValueError):
    pass


@dataclass(frozen=True)
class MonthlyOutcome:
    code: str
    counts: dict = field(default_factory=dict)


def window(today):
    if type(today) is not date:
        raise ValueError("월간 기준은 날짜여야 합니다")
    return today.replace(day=1), today - timedelta(days=1)


def _number(value, *, optional=False):
    if optional and value is None:
        return None
    if type(value) not in (int, float) or not 0 <= value <= MAX_NUMBER or not math.isfinite(value):
        raise CheckpointInvalid("월간 원천 숫자가 완결되지 않았습니다")
    if not optional and int(value) != value:
        raise CheckpointInvalid("월간 기본 지표가 정수가 아닙니다")
    return int(value) if int(value) == value else value


def fingerprint(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def _sum(rows):
    out = dict.fromkeys(FIELDS, 0)
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise CheckpointInvalid("월간 지표 모양이 다릅니다")
        for key in FIELDS:
            value = _number(row[key], optional=key == "convAmt")
            out[key] = None if value is None or out[key] is None else _number(out[key] + value, optional=key == "convAmt")
    return out


def validate_progress(source, customer_id, start, end):
    required = {"customer_id", "period_start", "period_end", "campaign_ids", "fingerprint", "next_index",
                "batches", "cycles", "zero_rows"}
    if not isinstance(source, dict) or set(source) != required or source["customer_id"] != customer_id \
            or type(source["customer_id"]) is not int or source["period_start"] != start.isoformat() \
            or source["period_end"] != end.isoformat() or start > end:
        raise CheckpointInvalid("월간 원천 기간 또는 계정이 다릅니다")
    ids, index = source["campaign_ids"], source["next_index"]
    if not isinstance(ids, list) or any(not isinstance(i, str) or not N._CAMPAIGN_ID.fullmatch(i) for i in ids) \
            or ids != sorted(set(ids)) or source["fingerprint"] != fingerprint(ids):
        raise CheckpointInvalid("월간 캠페인 목록 지문이 다릅니다")
    if type(index) is not int or not 0 <= index <= len(ids) or (index != len(ids) and index % N.STATS_IDS_PER_CALL):
        raise CheckpointInvalid("월간 이어읽기 위치가 다릅니다")
    batches, cycles = source["batches"], source["cycles"]
    if not isinstance(batches, list) or len(batches) != (index + N.STATS_IDS_PER_CALL - 1) // N.STATS_IDS_PER_CALL \
            or not isinstance(cycles, list) or len(cycles) != len(batches):
        raise CheckpointInvalid("월간 배치 수가 다릅니다")
    for raw in cycles:
        try:
            cycle = datetime.fromisoformat(raw)
            if cycle.tzinfo is None or cycle.astimezone(S.KST).date() <= end:
                raise ValueError()
        except (TypeError, ValueError):
            raise CheckpointInvalid("월간 자료 기준 시각이 완결되지 않았습니다") from None
    zeros = source["zero_rows"]
    if not isinstance(zeros, dict) or set(zeros) - set(ids):
        raise CheckpointInvalid("월간 무활동 근거의 번호가 다릅니다")
    for row in zeros.values():
        _sum([row])
        if any(row[key] != 0 for key in FIELDS[:3]):
            raise CheckpointInvalid("월간 무활동 근거가 아닙니다")
    totals = _sum(batches)
    if not ids:
        totals["convAmt"] = None  # 캠페인이 없음은 전환 추적 설정의 증거가 아니다.
    return totals


def _campaigns(raw):
    ids = sorted(c["nccCampaignId"] for c in raw)
    if len(ids) != len(set(ids)) or any(not N._CAMPAIGN_ID.fullmatch(i) for i in ids):
        raise N.StatsShapeUnknown("월간 캠페인 목록이 겹치거나 다릅니다")
    enabled = 0
    for campaign in raw:
        status, lock, deleted = campaign.get("status"), campaign.get("userLock"), campaign.get("delFlag", False)
        # 기존 점검이 확인한 정상값만 해석한다. 새 공급자 상태값을 비활성으로 추정하지 않는다.
        if status != "ELIGIBLE" or type(lock) is not bool or type(deleted) is not bool:
            enabled = None
            break
        enabled += status == "ELIGIBLE" and not lock and not deleted
    return ids, enabled


def _read(reader, handle, today, values, store, snapshot, clock):
    start, end = window(today)
    progress = store.monthly_progress(handle.customer_id, start, end)
    ids, enabled = _campaigns(reader.get_campaigns(handle))
    values.update(campaign_count=None if enabled is None else len(ids), enabled_campaigns=enabled,
                  campaign_fingerprint=fingerprint(ids))
    if progress is None or progress["campaign_ids"] != ids:
        progress = dict(customer_id=handle.customer_id, period_start=start.isoformat(), period_end=end.isoformat(),
                        campaign_ids=ids, fingerprint=fingerprint(ids), next_index=0, batches=[], cycles=[], zero_rows={})
        store.record_monthly_progress(handle.customer_id, snapshot, clock(), progress)
    while progress["next_index"] < len(ids):
        chunk = ids[progress["next_index"]:progress["next_index"] + N.STATS_IDS_PER_CALL]
        stats = reader.get_stats_summary(handle, chunk, start, end, fields=FIELDS)
        # 새 합계 줄이 있으면 재시도 전에 이전 0 근거부터 폐기한다.
        superseded = set(progress["zero_rows"]).intersection(stats.rows)
        if superseded:
            for key in superseded:
                del progress["zero_rows"][key]
            store.record_monthly_progress(handle.customer_id, snapshot, clock(), progress)
        reader.check_budget()
        if not stats.data_fresh:
            raise MonthlyIncomplete("월간 통계가 완결되지 않았습니다")
        rows = dict(stats.rows)
        try:
            _sum(rows.values())
        except CheckpointInvalid:
            raise MonthlyIncomplete("월간 기본 지표가 완결되지 않았습니다") from None
        for campaign_id in stats.missing_ids:
            if campaign_id not in progress["zero_rows"]:
                daily = reader.get_stats_daily(handle, campaign_id, start, end, fields=FIELDS)
                reader.check_budget()
                if not daily.data_fresh or daily.missing_days or not daily.days:
                    raise MonthlyIncomplete("월간 무활동 날짜가 완결되지 않았습니다")
                try:
                    zero = _sum(daily.days.values())
                except CheckpointInvalid:
                    raise MonthlyIncomplete("월간 무활동 지표가 완결되지 않았습니다") from None
                if any(zero[key] != 0 for key in FIELDS[:3]):
                    raise MonthlyIncomplete("월간 합계 누락을 0으로 확인하지 못했습니다")
                progress["zero_rows"][campaign_id] = zero
                store.record_monthly_progress(handle.customer_id, snapshot, clock(), progress)
                values["progressed"] = True
            rows[campaign_id] = progress["zero_rows"][campaign_id]
        if set(rows) != set(chunk):
            raise MonthlyIncomplete("월간 캠페인 합계가 완결되지 않았습니다")
        totals = _sum(rows.values())
        progress["batches"].append(totals)
        progress["cycles"].append(stats.cycle_base_tm.isoformat())
        progress["next_index"] += len(chunk)
        store.record_monthly_progress(handle.customer_id, snapshot, clock(), progress)
        values["progressed"] = True
    after, enabled = _campaigns(reader.get_campaigns(handle))
    if after != ids:
        values.update(status="retry", error_code="CAMPAIGNS_CHANGED")
        return
    totals = validate_progress(progress, handle.customer_id, start, end)
    values.update(status="ok", enabled_campaigns=enabled, campaign_count=None if enabled is None else len(ids))
    values.update(zip(OUTPUTS, (totals[key] for key in FIELDS)))


def run_monthly(reader, store, clock, *, limit=24, max_calls=24, max_seconds=30,
                per_account_calls=8, exclude_checked_after=None):
    if type(limit) is not int or not 1 <= limit <= 24 or type(max_calls) is not int or not 1 <= max_calls <= 24 \
            or type(max_seconds) not in (int, float) or not 0 < max_seconds <= 30 \
            or type(per_account_calls) is not int or not 1 <= per_account_calls <= 8:
        raise ValueError("월간 수집 예산이 올바르지 않습니다")
    now = clock()
    today = now.astimezone(S.KST).date()
    if window(today)[0] > window(today)[1]:
        return MonthlyOutcome("EMPTY_PERIOD")
    if reader.rate_limited:
        return MonthlyOutcome("BUDGET")
    snapshot = store.inventory_snapshot(now)
    if snapshot is None:
        return MonthlyOutcome("NOT_READY")
    counts, initial, started = Counter(), reader.calls, monotonic()
    with reader.bounded_requests(max_calls=max_calls, max_seconds=max_seconds):
        for cid in store.monthly_work(now, limit, exclude_checked_after=exclude_checked_after):
            elapsed = max((clock() - now).total_seconds(), monotonic() - started)
            if max_calls - (reader.calls - initial) < 2 or elapsed >= max_seconds:
                return MonthlyOutcome("BUDGET", dict(counts))
            if clock() < now or clock().astimezone(S.KST).date() != today:
                return MonthlyOutcome("SOURCE_CHANGED", dict(counts))
            values = {}
            try:
                store.begin_monthly_check(cid, snapshot, clock())
                handle = H.issue_inventory_handle(customer_id=cid, snapshot_at=snapshot, now=clock(),
                                                  validate=store.inventory_account_valid)
                with reader.bounded_requests(max_calls=per_account_calls, max_seconds=min(10, max_seconds - elapsed)):
                    _read(reader, handle, today, values, store, snapshot, clock)
                    reader.check_budget()
            except N.NaverApiError as exc:
                values.update(status="limited" if exc.kind == N.KIND_KEY_REJECTED else "retry", error_code=exc.kind)
            except (N.StatsShapeUnknown, MonthlyIncomplete):
                values.update(status="retry", error_code="STATS_INCOMPLETE")
            except CheckpointInvalid:
                values.update(status="limited", error_code="CHECKPOINT_INVALID")
            except N.RunAbort:
                values.update(status="partial" if values.get("progressed") else "retry", error_code="REQUEST_BUDGET")
            except (H.NotEligible, H.HandleInvalid, S.StoreRefused):
                return MonthlyOutcome("SOURCE_CHANGED", dict(counts))
            except S.StoreError:
                raise
            except Exception:
                values.update(status="retry", error_code="UNEXPECTED")
            try:
                status = store.record_monthly_check(cid, snapshot, clock(), values)
            except S.StoreRefused:
                return MonthlyOutcome("SOURCE_CHANGED", dict(counts))
            counts[status] += 1
            # 기존 재시도 결과는 저장하되 RATE를 겪은 회차에 새 월간 계정은 시작하지 않는다.
            if reader.rate_limited:
                return MonthlyOutcome("BUDGET", dict(counts))
    return MonthlyOutcome("DONE", dict(counts))
