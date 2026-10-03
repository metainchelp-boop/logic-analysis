"""광고 상태 원천을 한정된 읽기 예산으로 계층 순서대로 수집한다.

목록의 마지막 페이지와 상위 캠페인 재확인까지 끝나야 수집 완료이다. 정상 광고라는
판정은 하지 않는다. 각 원문 상태·사유와 실제 관측한 상위 관계/시각만 보존한다.
체크포인트에는 문구·이름·URL·사업자 정보가 없고, 재개 시 현재 위임을 매번 검사한다.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
from itertools import islice
import re
from time import monotonic

from . import ad_reasons as A, handles as H, naver_read as N, store as S


MAX_OBJECTS = 10000
MAX_TASKS = 10000
IDS = dict(A._ENTITY_IDS)
PARENTS = {"adgroup": "nccCampaignId", "ad": "nccAdgroupId", "keyword": "nccAdgroupId",
           "ad_extension": "ownerId"}
PAGED = {"adgroup", "keyword"}
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


class CheckpointInvalid(ValueError):
    """계정·상태 원문 등 입력값을 예외 문구로 노출하지 않는다."""


class StructureIncomplete(ValueError):
    pass


class StructureLimit(ValueError):
    pass


@dataclass(frozen=True)
class StructureOutcome:
    code: str
    counts: dict = field(default_factory=dict)


def _invalid():
    raise CheckpointInvalid("구조 원천의 계층·관계·이어읽기 근거가 다릅니다")


def _id(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _at(value, cycle_day):
    try:
        at = datetime.fromisoformat(value)
        if at.utcoffset() is None or at.astimezone(S.KST).date() < cycle_day:
            _invalid()
        return at
    except (TypeError, ValueError):
        _invalid()


def _record(entity, row):
    if not isinstance(row, dict) or not _id(row.get(IDS[entity])):
        _invalid()
    out = {IDS[entity]: row[IDS[entity]]}
    for name in ("status", "statusReason"):
        value = row.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > 160):
            _invalid()
        out[name] = value
    if entity in PARENTS:
        value = row.get(PARENTS[entity])
        if not _id(value):
            _invalid()
        out[PARENTS[entity]] = value
    return out


def _key(entity, record):
    return entity+":"+record[IDS[entity]]


def _fingerprint(records):
    roots = sorted((key, value["record"]) for key, value in records.items() if value["entity"] == "campaign")
    return hashlib.sha256(json.dumps(roots, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _task(entity, parent_id=None, parents=None, page_token=None):
    return {"entity": entity, "parent_id": parent_id, "cursor": page_token, "parents": parents or []}


def _task_key(task):
    return task["entity"], task["parent_id"], task["cursor"]


def _children(key, observation):
    entity, record = observation["entity"], observation["record"]
    parents = [key]+observation["parents"]
    identifier = record[IDS[entity]]
    if entity == "campaign":
        return [_task("adgroup", identifier, parents), _task("ad_extension", identifier, parents)]
    if entity == "adgroup":
        return [_task(name, identifier, parents) for name in ("ad", "keyword", "ad_extension")]
    if entity == "ad":
        return [_task("ad_extension", identifier, parents)]
    return []


def _relation(entity, parents, records, parent_id):
    if not isinstance(parents, list) or any(not isinstance(key, str) or key not in records for key in parents):
        _invalid()
    if entity in ("campaign", "business_channel"):
        if parents or parent_id is not None:
            _invalid()
        return
    if not parents or len(parents) > 3:
        _invalid()
    parent = records[parents[0]]
    permitted = {"adgroup": {"campaign"}, "ad": {"adgroup"}, "keyword": {"adgroup"},
                 "ad_extension": {"campaign", "adgroup", "ad"}}
    if parent["entity"] not in permitted[entity] or parents != [parents[0]]+parent["parents"] \
            or parent["record"][IDS[parent["entity"]]] != parent_id:
        _invalid()


def validate_progress(source, job):
    """저장소와 공유하는 엄격한 원천 검사. 표시 가능한 describe 결과 목록을 반환한다."""
    required = {"customer_id", "cycle_day", "campaign_fingerprint", "queue", "next_index", "records"}
    try:
        day = date.fromisoformat(job["cycle_day"])
        if not isinstance(source, dict) or set(source) != required or type(source["customer_id"]) is not int \
                or source["customer_id"] != job["customer_id"] or source["customer_id"] <= 0 \
                or source["cycle_day"] != job["cycle_day"]:
            _invalid()
        records, queue, index = source["records"], source["queue"], source["next_index"]
        if not isinstance(records, dict) or len(records) > MAX_OBJECTS or not isinstance(queue, list) \
                or not 1 <= len(queue) <= MAX_TASKS or type(index) is not int or not 0 <= index <= len(queue):
            _invalid()
        for key, observed in records.items():
            if not isinstance(observed, dict) or set(observed) != {"entity", "record", "checked_at", "parents"} \
                    or observed["entity"] not in IDS:
                _invalid()
            entity = observed["entity"]
            record = _record(entity, observed["record"])
            if record != observed["record"] or key != _key(entity, record):
                _invalid()
            _at(observed["checked_at"], day)
        for observed in records.values():
            entity = observed["entity"]
            _relation(entity, observed["parents"], records, observed["record"].get(PARENTS.get(entity)))
        if source["campaign_fingerprint"] != _fingerprint(records):
            _invalid()
        seen, processed = set(), set()
        for n, task in enumerate(queue):
            if not isinstance(task, dict) or set(task) != {"entity", "parent_id", "cursor", "parents"} \
                    or task["entity"] not in IDS or task["entity"] == "campaign":
                _invalid()
            entity, page_token = task["entity"], task["cursor"]
            _relation(entity, task["parents"], records, task["parent_id"])
            if page_token is not None:
                if entity not in PAGED or not _id(page_token) or entity+":"+page_token not in records:
                    _invalid()
                prior = records[entity+":"+page_token]
                if prior["parents"] != task["parents"] or (entity, task["parent_id"]) not in processed:
                    _invalid()
            key = _task_key(task)
            if key in seen:
                _invalid()
            seen.add(key)
            if n < index:
                processed.add((entity, task["parent_id"]))
        if ("business_channel", None, None) not in seen:
            _invalid()
        for key, observed in records.items():
            entity = observed["entity"]
            if entity != "campaign" and (entity, observed["record"].get(PARENTS.get(entity))) not in processed:
                _invalid()
            if any(_task_key(task) not in seen for task in _children(key, observed)):
                _invalid()
        return [A.describe(observed["entity"], observed["record"], checked_at=_at(observed["checked_at"], day),
                    parents=[(records[parent]["entity"], records[parent]["record"],
                              _at(records[parent]["checked_at"], day)) for parent in observed["parents"]])
                for _, observed in sorted(records.items())]
    except (KeyError, TypeError, ValueError):
        _invalid()


def _observe(entity, row, parents, now):
    try:
        record = _record(entity, row)
    except CheckpointInvalid:
        raise StructureIncomplete("구조 원천을 확인하지 못했습니다") from None
    return _key(entity, record), {"entity": entity, "record": record,
                                "checked_at": now.astimezone(S.KST).isoformat(), "parents": parents}


def _campaign_records(campaigns, now):
    records = {}
    if len(campaigns) > MAX_OBJECTS:
        raise StructureLimit("구조 원천의 수집 한도에 도달했습니다")
    for row in campaigns:
        key, observation = _observe("campaign", row, [], now)
        if key in records:
            raise StructureIncomplete("캠페인 원천 번호가 중복되었습니다")
        records[key] = observation
    return records


def _read(reader, handle, job, values, store, clock):
    progress = store.structure_progress(job)
    if progress is not None:
        validate_progress(progress, job)
        if any(datetime.fromisoformat(row["checked_at"]) > clock() for row in progress["records"].values()):
            _invalid()
    roots = _campaign_records(reader.get_campaigns(handle), clock())
    reader.check_budget()
    fingerprint = _fingerprint(roots)
    if progress is None or progress["campaign_fingerprint"] != fingerprint:
        queue = [_task("business_channel")]
        for key, observation in sorted(roots.items()):
            queue.extend(_children(key, observation))
        if len(queue) > MAX_TASKS:
            raise StructureLimit("구조 작업의 수집 한도에 도달했습니다")
        progress = {"customer_id": job["customer_id"], "cycle_day": job["cycle_day"],
                    "campaign_fingerprint": fingerprint, "queue": queue, "next_index": 0, "records": roots}
        store.record_structure_progress(job, clock(), progress)
    while progress["next_index"] < len(progress["queue"]):
        task = progress["queue"][progress["next_index"]]
        rows, next_token = reader.get_structure_page(handle, task["entity"], task["parent_id"],
                                                     page_token=task["cursor"])
        reader.check_budget()
        if len(progress["records"])+len(rows) > MAX_OBJECTS:
            raise StructureLimit("구조 원천의 수집 한도에 도달했습니다")
        update = deepcopy(progress)
        for row in rows:
            key, observation = _observe(task["entity"], row, task["parents"], clock())
            if key in update["records"]:
                raise StructureIncomplete("구조 원천 번호가 중복되거나 이동했습니다")
            update["records"][key] = observation
            update["queue"].extend(_children(key, observation))
        if next_token is not None:
            update["queue"].append({**task, "cursor": next_token})
        if len(update["queue"]) > MAX_TASKS:
            raise StructureLimit("구조 작업의 수집 한도에 도달했습니다")
        update["next_index"] += 1
        store.record_structure_progress(job, clock(), update)
        progress = update
        values["progressed"] = True
    after = _campaign_records(reader.get_campaigns(handle), clock())
    reader.check_budget()
    if _fingerprint(after) != fingerprint:
        values.update(status="retry", error_code="CAMPAIGNS_CHANGED")
        return
    values.update(status="ok", reasons=validate_progress(progress, job))


def run_structure(reader, store, clock, *, limit=24, max_calls=6, max_seconds=10, per_account_calls=6,
                  exclude_customers=()):
    if type(limit) is not int or not 1 <= limit <= 24 or type(max_calls) is not int or not 1 <= max_calls <= 24 \
            or type(max_seconds) not in (int, float) or not 0 < max_seconds <= 30 \
            or type(per_account_calls) is not int or not 1 <= per_account_calls <= 8:
        raise ValueError("구조 수집 예산이 올바르지 않습니다")
    try:
        excluded = tuple(islice(exclude_customers, MAX_OBJECTS+1))
        if len(excluded) > MAX_OBJECTS or any(type(cid) is not int or cid <= 0 for cid in excluded):
            raise ValueError()
        excluded = frozenset(excluded)
    except (TypeError, ValueError):
        raise ValueError("구조 중복 조회 제외 계정이 올바르지 않습니다") from None
    if reader.rate_limited:
        return StructureOutcome("BUDGET")
    now, initial, started, counts = clock(), reader.calls, monotonic(), Counter()
    with reader.bounded_requests(max_calls=max_calls, max_seconds=max_seconds):
        for job in store.structure_work(now, limit):
            if job["customer_id"] in excluded:
                continue
            elapsed = max((clock()-now).total_seconds(), monotonic()-started)
            if elapsed >= max_seconds or max_calls-(reader.calls-initial) < 2:
                return StructureOutcome("BUDGET", dict(counts))
            if clock() < now or clock().astimezone(S.KST).date() != now.astimezone(S.KST).date():
                return StructureOutcome("SOURCE_CHANGED", dict(counts))
            values = {}
            try:
                store.begin_structure_check(job, clock())
                handle = H.issue_inventory_handle(customer_id=job["customer_id"], snapshot_at=job["snapshot_at"],
                    now=clock(), validate=lambda cid, snapshot, at: store.structure_account_valid(job, at))
                with reader.bounded_requests(max_calls=per_account_calls, max_seconds=min(10, max_seconds-elapsed)):
                    _read(reader, handle, job, values, store, clock)
                    reader.check_budget()
            except N.NaverApiError as exc:
                values.update(status="reauth_required" if exc.kind == N.KIND_KEY_REJECTED else "retry", error_code=exc.kind)
            except (N.StatsShapeUnknown, StructureIncomplete):
                values.update(status="retry", error_code="STRUCTURE_INCOMPLETE")
            except StructureLimit:
                values.update(status="limited", error_code="STRUCTURE_LIMIT")
            except CheckpointInvalid:
                values.update(status="limited", error_code="CHECKPOINT_INVALID")
            except N.RunAbort as exc:
                values.update(status="partial" if values.get("progressed") else "retry",
                              error_code=N.KIND_RATE if reader.rate_limited else exc.cause_code or exc.code)
            except (H.NotEligible, H.HandleInvalid, S.StoreRefused):
                return StructureOutcome("SOURCE_CHANGED", dict(counts))
            except S.StoreError:
                raise
            except Exception:
                values.update(status="retry", error_code="UNEXPECTED")
            try:
                status = store.record_structure_check(job, clock(), values)
            except S.StoreRefused:
                return StructureOutcome("SOURCE_CHANGED", dict(counts))
            counts[status] += 1
            if reader.rate_limited:
                return StructureOutcome("BUDGET", dict(counts))
    return StructureOutcome("DONE", dict(counts))
