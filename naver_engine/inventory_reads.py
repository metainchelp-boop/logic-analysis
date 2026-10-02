"""대행 위임 계정 원천 읽기. 매칭·계약·ERP 전송 및 기존 점검 이력을 변경하지 않는다."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
import hashlib
import json
import math

from . import handles as H, naver_read as N, store as S


@dataclass(frozen=True)
class InventoryOutcome:
    code: str
    counts: dict = field(default_factory=dict)


FIELDS = ("impCnt", "clkCnt", "salesAmt")
MAX_NUMBER = 9007199254740991


class CheckpointInvalid(ValueError):
    pass


def _integer(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_NUMBER or int(value) != value:
        raise CheckpointInvalid("원천 합계가 완결된 정수가 아닙니다")
    return int(value)


def _fingerprint(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def validate_progress(source, customer_id, day):
    """저장된 목록 지문·배치 경계·정수 합계가 서로 맞아야 이어 읽는다."""
    required = {"customer_id", "day", "campaign_ids", "fingerprint", "next_index", "batches"}
    if not isinstance(source, dict) or set(source) not in (required, required | {"zero_ids"}):
        raise CheckpointInvalid("원천 이어읽기 모양이 아닙니다")
    if type(source["customer_id"]) is not int or source["customer_id"] != customer_id or source["day"] != day.isoformat():
        raise CheckpointInvalid("다른 계정 또는 날짜의 원천입니다")
    ids, index, batches = source["campaign_ids"], source["next_index"], source["batches"]
    if not isinstance(ids, list) or any(not isinstance(i, str) or not N._CAMPAIGN_ID.fullmatch(i) for i in ids) \
            or ids != sorted(set(ids)) or source["fingerprint"] != _fingerprint(ids):
        raise CheckpointInvalid("원천 목록 지문이 다릅니다")
    zero_ids = source.get("zero_ids", [])
    if not isinstance(zero_ids, list) or any(not isinstance(i, str) for i in zero_ids) \
            or zero_ids != sorted(set(zero_ids)) or not set(zero_ids).issubset(ids):
        raise CheckpointInvalid("원천 무활동 증거의 번호가 다릅니다")
    if type(index) is not int or not 0 <= index <= len(ids) or (index != len(ids) and index % N.STATS_IDS_PER_CALL):
        raise CheckpointInvalid("원천 이어읽기 위치가 다릅니다")
    if not isinstance(batches, list) or len(batches) != (index + N.STATS_IDS_PER_CALL - 1) // N.STATS_IDS_PER_CALL:
        raise CheckpointInvalid("원천 배치 수가 다릅니다")
    totals = dict.fromkeys(FIELDS, 0)
    for batch in batches:
        if not isinstance(batch, dict) or set(batch) != set(FIELDS):
            raise CheckpointInvalid("원천 배치 지표가 다릅니다")
        for name in FIELDS:
            totals[name] = _integer(totals[name] + _integer(batch[name]))
    return totals


def _read(reader, ah, today, values, per_account_calls, store, snapshot, clock):
    progress = store.inventory_progress(ah.customer_id, today)
    started_calls = reader.calls
    campaigns = reader.get_campaigns(ah)
    ids = sorted(c["nccCampaignId"] for c in campaigns)
    if len(ids) != len(set(ids)) or any(not N._CAMPAIGN_ID.fullmatch(i) for i in ids):
        raise N.StatsShapeUnknown("캠페인 목록이 겹치거나 다릅니다")
    values["campaigns"] = campaigns
    values["bizmoney"] = reader.get_bizmoney(ah)["bizmoney"]
    if progress is None or progress["campaign_ids"] != ids:
        progress = dict(customer_id=ah.customer_id, day=today.isoformat(), campaign_ids=ids,
                        fingerprint=_fingerprint(ids), next_index=0, batches=[])
        store.record_inventory_progress(ah.customer_id, snapshot, clock(), progress)
    yday = today - timedelta(days=1)
    while progress["next_index"] < len(ids):
        if reader.calls - started_calls >= per_account_calls:
            values.update(status="partial", error_code="CHECKPOINT_PENDING")
            return
        start = progress["next_index"]
        chunk = ids[start:start + N.STATS_IDS_PER_CALL]
        stats = reader.get_stats_summary(ah, chunk, yday, yday, fields=FIELDS)
        zero_ids = set(progress.get("zero_ids", []))
        superseded = zero_ids.intersection(stats.rows)
        if superseded:
            # 새 합계 줄이 있으면 이전 0 증거는 폐기한다. 뒤에서 재시도하더라도
            # 오래된 0이 부활하지 않게 먼저 저장하며, 폐기 자체는 진전이 아니다.
            zero_ids.difference_update(superseded)
            progress["zero_ids"] = sorted(zero_ids)
            store.record_inventory_progress(ah.customer_id, snapshot, clock(), progress)
        reader.check_budget()
        if not stats.data_fresh or stats.unknown_values:
            values.update(status="retry", error_code="STATS_INCOMPLETE")
            return
        rows = dict(stats.rows)
        # 합계에서 빠진 줄만 재확인한다. 날짜별 모든 지표가 완결된 0일 때만 보완한다.
        for cid in stats.missing_ids:
            if cid not in zero_ids:
                confirmed = reader.confirm_no_activity(ah, (cid,), yday, yday, fields=FIELDS)
                reader.check_budget()
                if not confirmed[cid]:
                    values.update(status="retry", error_code="STATS_INCOMPLETE")
                    return
                zero_ids.add(cid)
                progress["zero_ids"] = sorted(zero_ids)
                store.record_inventory_progress(ah.customer_id, snapshot, clock(), progress)
                values["progressed"] = True
            rows[cid] = dict.fromkeys(FIELDS, 0)
        if set(rows) != set(chunk):
            values.update(status="retry", error_code="STATS_INCOMPLETE")
            return
        batch = {name: _integer(sum(_integer(row[name]) for row in rows.values())) for name in FIELDS}
        progress["batches"].append(batch)
        progress["next_index"] += len(chunk)
        store.record_inventory_progress(ah.customer_id, snapshot, clock(), progress)
        values["progressed"] = True
    # 마지막 배치 뒤 목록이 바뀌었다면 누락/중복 합계를 공개하지 않는다.
    if reader.calls - started_calls >= per_account_calls:
        values.update(status="partial", error_code="CHECKPOINT_PENDING")
        return
    after = reader.get_campaigns(ah)
    if sorted(c["nccCampaignId"] for c in after) != ids:
        values.update(status="retry", error_code="CAMPAIGNS_CHANGED")
        return
    totals = validate_progress(progress, ah.customer_id, today)
    values["status"] = "ok"
    for source, target in zip(FIELDS, ("yday_imp", "yday_clk", "yday_spend")):
        values[target] = totals[source]


def run_inventory(reader, store, clock, *, limit=24, max_seconds=30, max_calls=24, per_account_calls=8):
    if type(limit) is not int or not 1 <= limit <= 24 or type(max_seconds) not in (int, float) \
            or not 0 < max_seconds <= 30 or type(max_calls) is not int or not 1 <= max_calls <= 24 \
            or type(per_account_calls) is not int or not 1 <= per_account_calls <= 8:
        raise ValueError("계정 원천 수집 예산이 올바르지 않습니다")
    now = clock()
    snapshot = store.inventory_snapshot(now)
    if snapshot is None:
        return InventoryOutcome("NOT_READY")
    counts = Counter()
    initial_calls, started = reader.calls, monotonic()
    today = now.astimezone(S.KST).date()
    with reader.bounded_requests(max_calls=max_calls, max_seconds=max_seconds):
        for cid in store.inventory_work(now, limit):
            elapsed = max((clock() - now).total_seconds(), monotonic() - started)
            # 빈 계정도 목록/잔액/마지막 목록의 3회가 필요하다. 남은 예산이
            # 그보다 작으면 새 계정의 실패 횟수를 불필요하게 소모하지 않는다.
            if elapsed >= max_seconds or max_calls - (reader.calls - initial_calls) < 3:
                return InventoryOutcome("BUDGET", dict(counts))
            if clock() < now or clock().astimezone(S.KST).date() != today:
                return InventoryOutcome("SOURCE_CHANGED", dict(counts))
            values = {}
            try:
                store.begin_inventory_check(cid, snapshot, clock())
                ah = H.issue_inventory_handle(customer_id=cid, snapshot_at=snapshot, now=clock(),
                                              validate=store.inventory_account_valid)
                with reader.bounded_requests(max_calls=per_account_calls, max_seconds=min(10, max_seconds - elapsed)):
                    _read(reader, ah, today, values, per_account_calls, store, snapshot, clock)
                    reader.check_budget()
            except N.NaverApiError as exc:
                values.update(status="reauth_required" if exc.kind == N.KIND_KEY_REJECTED else "retry",
                              error_code=exc.kind)
            except N.StatsShapeUnknown:
                values.update(status="retry", error_code="STATS_SHAPE")
            except CheckpointInvalid:
                values.update(status="limited", error_code="CHECKPOINT_INVALID")
            except N.RunAbort:
                values.update(status="partial" if values.get("progressed") else "retry", error_code="REQUEST_BUDGET")
            except (H.NotEligible, H.HandleInvalid, S.StoreRefused):
                return InventoryOutcome("SOURCE_CHANGED", dict(counts))
            except S.StoreError:
                raise
            except Exception:
                values.update(status="retry", error_code="UNEXPECTED")
            try:
                status = store.record_inventory_check(cid, snapshot, clock(), values)
            except S.StoreRefused:
                return InventoryOutcome("SOURCE_CHANGED", dict(counts))
            counts[status] += 1
    return InventoryOutcome("DONE", dict(counts))
