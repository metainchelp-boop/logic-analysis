"""저장된 광고 상태와 계획 기록만 읽는 순수 세팅 점검 projection.

``structure``는 Store.structure_checks()[customer_id]의 결과다. ``ok``는
구조 수집의 완결성만 뜻하며 광고 설정이나 운영의 적정성을 보증하지 않는다.
캠페인 원문을 연결할 때는 campaigns_json과 함께 campaign_source의
status='ok', complete=True, stale=False, checked_at을 제공해야 한다.
stale=False는 호출자가 현재 계정·관리 단계·수집 회차를 대조한 결과여야 한다.
이 모듈은 계정 권한을 발급하거나 원천을 수집하지 않는다.
``observation``이 있으면 Store가 현재 권한·계약 단계·수집 회차로 검증한
공유 점검 자료를 우선한다. 최신 실패·대기는 이전 성공 자료로 대신하지 않는다.
"""
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import math
import re

from . import ad_reasons as A
from . import shared_budget_evidence as B


STATES = ("attention", "unknown", "verified", "not_applicable")
_MAX_ROWS = 10000
_DETAIL_LIMIT = 100
_MAX_AGE = timedelta(days=7)  # 저장소의 회차 판정에 더해 주간 수집의 외곽 한도만 확인한다.
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_OBS_KEYS = {"source", "entity", "entity_id", "checked_at", "status", "reason", "parents"}
_INSPECTION = frozenset(code for code in A._REASONS
    if code.endswith(("_DISAPPROVED", "_DENIED", "_UNDER_REVIEW")))
_SUSPENSION = frozenset(code for code in A._REASONS if code.endswith(("_PAUSED", "_DELETED")))
_DELIVERY = frozenset(code for code in A._REASONS
    if code.endswith(("_ABNORMAL_INTERLOCK", "_LIMITED_BY_BUDGET"))) | {
        "GROUP_PAUSED_BY_INVALID_TARGET", "LACK_OF_ACCOUNT_BALANCE", "REFUND_IN_PROGRESS"}


def _at(value):
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value)
        return at if at.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _meta(source, now, *, structure=False):
    source = source if isinstance(source, Mapping) else {}
    at = _at(source.get("checked_at"))
    complete = source.get("status") == "ok" and source.get("complete", structure) is True
    current = source.get("stale") is False and at is not None and timedelta(0) <= now-at <= _MAX_AGE
    return {"status": source.get("status") if source.get("status") in
            ("ok", "pending", "reading", "partial", "retry", "failed", "limited", "reauth_required") else "unknown",
            "checked_at": at.isoformat() if at else None, "complete": complete,
            "freshness": "current" if current else "stale" if source.get("stale") is True or
                (at is not None and now-at > _MAX_AGE) else "unknown",
            "usable": complete and current}


def _observation(row, *, now, checked_at, parent=False):
    if not isinstance(row, dict) or set(row) != _OBS_KEYS or row.get("entity") not in A._ENTITY_IDS \
            or not isinstance(row.get("entity_id"), str) or not _ID.fullmatch(row["entity_id"]):
        raise ValueError()
    at = _at(row.get("checked_at"))
    if at is None or not timedelta(0) <= now-at <= _MAX_AGE or at > checked_at:
        raise ValueError()
    if not isinstance(row.get("parents"), list) or len(row["parents"]) > 3 or (parent and row["parents"]):
        raise ValueError()
    if any(not isinstance(row.get(key), dict) for key in ("status", "reason")):
        raise ValueError()
    record = {A._ENTITY_IDS[row["entity"]]: row["entity_id"],
              "status": row["status"].get("code"), "statusReason": row["reason"].get("code")}
    if any(code is not None and (not isinstance(code, str) or len(code) > 160)
           for code in (record["status"], record["statusReason"])):
        raise ValueError()
    canonical = A.describe(row["entity"], record, checked_at=at)
    if {key: value for key, value in row.items() if key != "parents"} != \
            {key: value for key, value in canonical.items() if key != "parents"}:
        raise ValueError()
    for ancestor in row["parents"]:
        _observation(ancestor, now=now, checked_at=checked_at, parent=True)


def _observations(structure, meta, now):
    if not meta["usable"]:
        return None
    rows = structure.get("reasons")
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        return None
    try:
        checked_at = _at(meta["checked_at"])
        by_key = {}
        for row in rows:
            _observation(row, now=now, checked_at=checked_at)
            key = (row["entity"], row["entity_id"])
            if key in by_key:
                raise ValueError()
            by_key[key] = row
        for row in rows:
            kinds = [ancestor["entity"] for ancestor in row["parents"]]
            expected = {"campaign": [], "business_channel": [], "adgroup": ["campaign"],
                        "ad": ["adgroup", "campaign"], "keyword": ["adgroup", "campaign"]}
            if row["entity"] == "ad_extension":
                if kinds not in (["campaign"], ["adgroup", "campaign"], ["ad", "adgroup", "campaign"]):
                    raise ValueError()
            elif kinds != expected[row["entity"]]:
                raise ValueError()
            for index, ancestor in enumerate(row["parents"]):
                actual = by_key.get((ancestor["entity"], ancestor["entity_id"]))
                if actual is None or {**actual, "parents": []} != ancestor or \
                        actual["parents"] != row["parents"][index+1:]:
                    raise ValueError()
        return rows
    except (KeyError, TypeError, ValueError):
        return None


def _campaigns(campaigns, meta):
    if not meta["usable"] or not isinstance(campaigns, list) or len(campaigns) > _MAX_ROWS:
        return None
    ids = set()
    for row in campaigns:
        if not isinstance(row, dict) or not isinstance(row.get("nccCampaignId"), str) or \
                not _ID.fullmatch(row["nccCampaignId"]) or row["nccCampaignId"] in ids:
            return None
        ids.add(row["nccCampaignId"])
    return campaigns


def _item(key, label, state, summary, next_action):
    return {"key": key, "label": label, "state": state, "summary": summary, "next_action": next_action}


def _status_item(key, label, codes, rows):
    if rows is None or not rows:
        return _item(key, label, "unknown", "현재 회차의 완결된 광고 상태 근거가 부족합니다.",
                     "광고 상태의 수집 완결성과 확인 시각을 확인하세요.")
    matches = [row for row in rows if row["reason"]["code"] in codes]
    unknown = sum(row["reason"]["code_state"] != "known" for row in rows)
    if matches:
        reasons = sorted({row["reason"]["meaning"] for row in matches})
        suffix = f" 상세 사유 미확인 {unknown}개가 별도로 있습니다." if unknown else ""
        return _item(key, label, "attention", f"관측 대상 {len(matches)}개: {' · '.join(reasons)}.{suffix}",
                     "의도한 운영 상태인지 확인하고 필요한 보완을 검토하세요. 설정 오류나 재개 필요를 단정하지 않습니다.")
    if unknown:
        return _item(key, label, "unknown", f"상세 사유 {unknown}개를 해석할 근거가 부족합니다.",
                     "미제공 또는 미확인 상태 사유를 확인하세요.")
    return _item(key, label, "verified", "수집된 상세 사유에서 이 항목의 확인 필요 코드는 관측되지 않았습니다.",
                 "현재 수집 범위에 한한 결과입니다. 전체 설정의 적정성은 별도로 검토하세요.")


def _amount(value):
    if type(value) is int:
        return 0 <= value <= 10**15
    return type(value) is float and math.isfinite(value) and 0 <= value <= 10**15


def _shared_budget_state(raw):
    """Observed shared-budget evidence; absence never proves nonshared use."""
    shared = "unknown" if "sharedBudgetId" not in raw else "none" if raw["sharedBudgetId"] is None else "shared"
    if raw.get("sharedBudgetLock") is True or (type(raw.get("sharedDailyBudget")) in (int, float)
            and raw["sharedDailyBudget"] > 0):
        shared = "shared"
    return shared


def _budget_item(rows, proof=None, now=None):
    if rows:
        shared = Counter(B.resolved(row, proof, now) for row in rows)
        summary = (f"공유예산 관련 값 있음 {shared['shared']}개 · 사용 안 함 확인 {shared['none']}개 · "
                   f"공유예산 미확인 {shared['unknown']}개")
        counts = Counter()
        for row in rows:
            if B.resolved(row, proof, now) == "shared":
                if not _amount(row.get("sharedDailyBudget")):
                    break
            elif row.get("useDailyBudget") is False:
                counts["unused"] += 1
            elif row.get("useDailyBudget") is True and _amount(row.get("dailyBudget")):
                counts["daily"] += 1
            else:
                break
        else:
            return _item("campaign_budget", "캠페인 예산 설정", "unknown" if shared["unknown"] else "verified",
                f"일예산 사용 {counts['daily']}개 · 일예산 미사용 {counts['unused']}개 · {summary}를 관측했습니다.",
                "일예산 미사용 자체는 오류가 아닙니다. 공유예산 미확인은 미사용 확인이 아닙니다. "
                "계획 대비 적정 금액·승인·실집행은 별도 확인하세요.")
        return _item("campaign_budget", "캠페인 예산 설정", "unknown",
                     f"일부 캠페인의 예산 금액·사용 여부를 확인하지 못했습니다. {summary}를 관측했습니다.",
                     "예산 필드가 있는 저장 원문과 완결성·확인 시각을 연결하세요.")
    return _item("campaign_budget", "캠페인 예산 설정", "unknown", "확인 가능한 최신 캠페인 예산 원문이 부족합니다.",
                 "예산 필드가 있는 저장 원문과 완결성·확인 시각을 연결하세요.")

def _period_value(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value) if len(value) == 10 else _at(value)
    except ValueError:
        return None


def _period_item(rows):
    if rows:
        limited = 0
        for row in rows:
            if row.get("usePeriod") is False:
                continue
            start, end = _period_value(row.get("periodStartDt")), _period_value(row.get("periodEndDt"))
            if row.get("usePeriod") is not True or start is None or end is None or type(start) is not type(end) or start > end:
                break
            limited += 1
        else:
            return _item("campaign_period", "캠페인 노출 기간", "verified",
                f"노출 기간 사용 {limited}개 · 기간 제한 없음 {len(rows)-limited}개를 관측했습니다.",
                "기간 제한 없음이나 시작 전·종료 후 상태만으로 설정 오류를 단정하지 않습니다. 계획과 대조하세요.")
    return _item("campaign_period", "캠페인 노출 기간", "unknown", "확인 가능한 최신 캠페인 기간 원문이 부족합니다.",
                 "기간 필드가 있는 저장 원문과 완결성·확인 시각을 연결하세요.")


_ENTITY_LABELS = {"campaign": "캠페인", "adgroup": "광고그룹", "keyword": "키워드", "ad": "소재"}
_TARGETS = {"SD": ("time_targeting", "요일·시간 설정"), "RL": ("region_targeting", "지역 설정"),
            "AG": ("age_targeting", "연령 설정"), "negative_keywords": ("negative_keywords", "제외 검색어")}
_DISPLAY_SETTINGS = ("name", "keyword", "campaignTp", "adgroupType", "type", "useDailyBudget", "dailyBudget",
    "sharedDailyBudget", "usePeriod", "periodStartDt", "periodEndDt", "bidAmt", "useGroupBidAmt", "userLock",
    "status", "statusReason", "title", "description", "headline", "text")
_METRICS = ("impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt")


def _text(value, limit=200):
    return value if isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 for c in value) else None


def _generation(value):
    return value if type(value) is int and 0 <= value <= 10**15 else _text(value, 100)


def _settings(raw):
    """Only bounded display fields; customer/business identifiers and URLs never leave this projection."""
    if not isinstance(raw, Mapping):
        return {}
    out = {key: value for key in _DISPLAY_SETTINGS if (value := raw.get(key)) is not None and
           (type(value) is bool or _amount(value) or _text(value, 1000) is not None)}
    creative = raw.get("ad")
    if isinstance(creative, Mapping):
        for key in ("title", "description", "headline", "text"):
            if _text(creative.get(key), 1000) is not None:
                out[key] = creative[key]
    attrs = raw.get("adgroupAttrJson")
    if isinstance(attrs, Mapping) and type(attrs.get("useAdvoost")) is bool:
        out["useAdvoost"] = attrs["useAdvoost"]
    return out


def _path(entity, entities):
    parts = []
    for kind, identifier in (("campaign", entity.get("campaign_id")),
            ("adgroup", entity.get("parent_id") if entity["entity"] in ("keyword", "ad") else
             entity["id"] if entity["entity"] == "adgroup" else None), (entity["entity"], entity["id"])):
        if not identifier or any(part["id"] == identifier and part["entity"] == kind for part in parts):
            continue
        raw = entities.get(f"{kind}:{identifier}", {}).get("settings", {})
        parts.append({"entity": kind, "id": identifier,
                      "name": _text(raw.get("name")) or _text(raw.get("keyword")) or None})
    return parts


def _shared_entities(observation, meta, now):
    if not meta["usable"] or type(observation.get("version")) is not int or observation.get("version") != 1:
        return None
    campaigns, entities = observation.get("campaigns"), observation.get("entities")
    if _campaigns(campaigns, meta) is None or not isinstance(entities, Mapping) or len(entities) > _MAX_ROWS:
        return None
    at = _at(meta["checked_at"])
    campaign_ids = {row["nccCampaignId"] for row in campaigns}
    for key, row in entities.items():
        if not isinstance(row, Mapping) or row.get("entity") not in _ENTITY_LABELS or not isinstance(row.get("id"), str) \
                or not _ID.fullmatch(row["id"]) or key != f'{row["entity"]}:{row["id"]}':
            return None
        kind, identifier, raw = row["entity"], row["id"], row.get("settings")
        observed_at = _at(row.get("checked_at"))
        if not isinstance(raw, Mapping) or raw.get(A._ENTITY_IDS[kind]) != identifier or observed_at is None \
                or not timedelta(0) <= now-observed_at <= _MAX_AGE or observed_at > at:
            return None
        cid = observation.get("customer_id")
        if cid is not None and raw.get("customerId") is not None and str(raw["customerId"]) != str(cid):
            return None
        campaign_id, parent_id = row.get("campaign_id"), row.get("parent_id")
        if not isinstance(campaign_id, str) or not _ID.fullmatch(campaign_id) or \
                parent_id is not None and (not isinstance(parent_id, str) or not _ID.fullmatch(parent_id)) or \
                any(value is not None and _text(value, 160) is None for value in (raw.get("status"), raw.get("statusReason"))):
            return None
        if kind == "campaign":
            if identifier not in campaign_ids or campaign_id != identifier or parent_id is not None:
                return None
        elif campaign_id not in campaign_ids or f"campaign:{campaign_id}" not in entities:
            return None
        elif kind == "adgroup":
            if parent_id != campaign_id or raw.get("nccCampaignId") != campaign_id:
                return None
        else:
            parent = entities.get(f"adgroup:{parent_id}", {})
            if parent.get("campaign_id") != campaign_id or raw.get("nccAdgroupId") != parent_id:
                return None
    if any(f"campaign:{identifier}" not in entities for identifier in campaign_ids):
        return None
    if any(entities[f'campaign:{row["nccCampaignId"]}']["settings"] != row for row in campaigns):
        return None
    return entities


def project_existing_budget(*, now, observation=None):
    """Current saved campaign limits for a local plan draft; never an approval.

    Units are deliberately unconfirmed. The two amounts are calculation choices,
    not evidence of an account-wide contractual budget or an execution unit.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("예산 점검 시각에는 시간대가 필요합니다")
    out = dict(version=1, status="unavailable", checked_at=None, generation=None,
        campaigns=[], groups=[], campaign_total=None, group_total=None, rows_truncated=False,
        candidate_amounts={"vat_included_krw": None, "vat_excluded_krw": None},
        can_prefill=False, reason_codes=["SOURCE_UNAVAILABLE"], source_unit="unconfirmed",
        execution_enabled=False)
    source = observation if isinstance(observation, Mapping) else {}
    meta = _meta(source, now)
    entities = _shared_entities(source, meta, now)
    if entities is None:
        return out
    # The Store has already bound this observation to the selected account and
    # stage. Do not expose IDs or borrow an older/partial observation here.
    cid, pid = source.get("customer_id"), source.get("possibility_id")
    if type(cid) is not int or cid <= 0 or type(pid) is not int or pid <= 0 or any(
            type(row["settings"].get("customerId")) not in (int, str) or
            str(row["settings"]["customerId"]) != str(cid) for row in entities.values()):
        return out
    out.update(status="ready", checked_at=meta["checked_at"], generation=_generation(source.get("generation")),
        reason_codes=[])
    proof = B.from_observation(source, now)
    labels = {}
    for kind in ("campaign", "adgroup"):
        for index, row in enumerate(sorted((row for row in entities.values() if row["entity"] == kind),
                                         key=lambda row: row["id"]), 1):
            labels[(kind, row["id"])] = _text(row["settings"].get("name"), 200) or \
                ("캠페인" if kind == "campaign" else "광고그룹") + f" {index}"

    def public(row):
        raw = row["settings"]
        value = raw.get("dailyBudget")
        amount = value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1e9 else None
        shared = B.resolved(raw, proof, now) if row["entity"] == "campaign" else _shared_budget_state(raw)
        return dict(label=labels[(row["entity"], row["id"])],
            parent_label=labels.get(("campaign", row["campaign_id"])) if row["entity"] == "adgroup" else None,
            budget=amount, budget_present="dailyBudget" in raw,
            use_daily_budget=raw.get("useDailyBudget") if type(raw.get("useDailyBudget")) is bool else None,
            shared_budget=shared, user_lock=raw.get("userLock") if type(raw.get("userLock")) is bool else None,
            deleted=raw.get("delFlag") if type(raw.get("delFlag")) is bool else None,
            status=_text(raw.get("status"), 160))

    campaigns = [public(row) for row in sorted(entities.values(), key=lambda row: row["id"])
                 if row["entity"] == "campaign"]
    groups = [public(row) for row in sorted(entities.values(), key=lambda row: row["id"])
              if row["entity"] == "adgroup"]
    out.update(campaigns=campaigns[:_DETAIL_LIMIT], groups=groups[:_DETAIL_LIMIT],
        campaign_total=len(campaigns), group_total=len(groups),
        rows_truncated=len(campaigns) > _DETAIL_LIMIT or len(groups) > _DETAIL_LIMIT)
    if not campaigns:
        out["reason_codes"].append("NO_CAMPAIGNS")
    if out["rows_truncated"]:
        out["reason_codes"].append("DISPLAY_TRUNCATED")
    for row in campaigns:
        if row["use_daily_budget"] is not True:
            out["reason_codes"].append("FINITE_BUDGET_UNCONFIRMED")
        if row["budget"] is None or row["budget"] < 70 or not float(row["budget"]).is_integer():
            out["reason_codes"].append("AMOUNT_UNCONFIRMED")
        if row["shared_budget"] != "none":
            out["reason_codes"].append("NONSHARED_UNCONFIRMED")
    if not out["reason_codes"]:
        total = sum(Decimal(str(row["budget"])) for row in campaigns)
        # Same fixed unit protocol as execution_commands._budget_factor.
        amounts = {"vat_included_krw": total, "vat_excluded_krw": total * Decimal("1.1")}
        if any(value > Decimal("1e12") for value in amounts.values()):
            out["reason_codes"].append("PLAN_AMOUNT_LIMIT")
        else:
            out["candidate_amounts"] = {unit: float(value) for unit, value in amounts.items()}
            out["can_prefill"] = True
    out["reason_codes"] = list(dict.fromkeys(out["reason_codes"]))
    return out


def _shared_reasons(entities):
    out = []
    for row in entities.values():
        parents = []
        if row["entity"] in ("keyword", "ad"):
            parents.append(entities[f'adgroup:{row["parent_id"]}'])
        if row["entity"] != "campaign":
            parents.append(entities[f'campaign:{row["campaign_id"]}'])
        try:
            out.append(A.describe(row["entity"], row["settings"], checked_at=_at(row["checked_at"]),
                parents=[(parent["entity"], parent["settings"], _at(parent["checked_at"])) for parent in parents]))
        except (TypeError, ValueError):
            return None
    return out


def _metric_detail(raw, now, at):
    if not isinstance(raw, Mapping):
        return None
    checked, source = _at(raw.get("checked_at")), _at(raw.get("source_at"))
    start, end = _period_value(raw.get("period_start")), _period_value(raw.get("period_end"))
    fields = raw.get("fields")
    if checked is None or not timedelta(0) <= now-checked <= _MAX_AGE or checked > at \
            or raw.get("source_at") is not None and source is None or source is not None and source > checked \
            or type(start) is not date or type(end) is not date or start > end or end >= now.astimezone(timezone(timedelta(hours=9))).date() or not isinstance(fields, Mapping) \
            or set(fields) - set(_METRICS) or any(value is not None and not _amount(value) for value in fields.values()):
        return None
    missing = raw.get("missing") is True
    cutoff = datetime.combine(end, datetime.min.time(), timezone(timedelta(hours=9)))+timedelta(days=1)
    current = source is not None and timedelta(0) <= now-source <= _MAX_AGE and source >= cutoff
    shown_fields = {key: fields.get(key) if current and not missing else None for key in _METRICS}
    # Null/missing stays unknown even when a caller accidentally labels the row complete.
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "checked_at": checked.isoformat(),
            "source_at": source.isoformat() if source else None, "fields": shown_fields, "missing": missing,
            "complete": raw.get("complete") is True and current and not missing and all(_amount(fields.get(key)) for key in _METRICS),
            "reason": "응답 자료 없음" if missing else "기간 종료 후의 최신 원천 시각 미확인" if not current else "관측한 성과 범위"}


def _target_records(raw):
    if not isinstance(raw, list) or len(raw) > _MAX_ROWS:
        return None
    out = []
    for record in raw:
        if not isinstance(record, Mapping):
            return None
        item = {key: value for key in ("type", "value", "dictionaryCode", "codeName", "bidWeight", "negative",
                "enable", "delFlag", "keyword") if (value := record.get(key)) is not None and
                (type(value) is bool or _amount(value) or _text(value, 500) is not None)}
        if len(out) < 20:
            out.append(item)
    return out


def _target_details(observation, entities, meta, now):
    raw = observation.get("targets")
    if not isinstance(raw, Mapping) or len(raw) > _MAX_ROWS:
        return {}
    out = {}
    for group_id, values in raw.items():
        group = entities.get(f"adgroup:{group_id}")
        if group is None or not isinstance(values, Mapping):
            continue
        for kind in _TARGETS:
            record = values.get(kind)
            if not isinstance(record, Mapping) or record.get("state") not in ("observed", "unsupported"):
                continue
            at = _at(record.get("checked_at"))
            rows = _target_records(record.get("records"))
            if at is None or not timedelta(0) <= now-at <= _MAX_AGE or at > _at(meta["checked_at"]) or rows is None:
                continue
            from .inspection_fields import capabilities, valid_target_constraints
            group_type = group["settings"].get("adgroupType")
            capability = capabilities(group_type).get(kind, "unknown")
            if record["state"] == "unsupported" and (capability != "unsupported" or record["records"]):
                continue
            if record["state"] == "observed" and capability != "supported":
                continue
            if record["state"] == "observed" and not valid_target_constraints(record["records"], group_type, kind):
                continue
            if len(out) >= _DETAIL_LIMIT:
                # Keep full summary counts without expanding every group's
                # paths/record display dictionaries into the response.
                out[(group_id, kind)] = {"state": record["state"], "record_total": len(record["records"])}
                continue
            managed = group["settings"].get("adgroupType") == "LOCAL_AD" and \
                isinstance(group["settings"].get("adgroupAttrJson"), Mapping) and \
                group["settings"]["adgroupAttrJson"].get("useAdvoost") is True
            out[(group_id, kind)] = {"entity": "adgroup", "id": group_id, "kind": kind, "state": record["state"],
                "path": _path(group, entities), "checked_at": at.isoformat(), "records": rows,
                "record_total": len(record["records"]), "records_truncated": len(record["records"]) > len(rows),
                "reason": "유형상 미지원으로 확인된 항목입니다." if record["state"] == "unsupported" else
                    "명시 설정이 없습니다. 기본 설정 관측이며 미수집과 다릅니다." if not record["records"] else "명시 설정을 관측했습니다.",
                "next_action": "ADVoost 플랫폼 관리 항목의 수동 변경 제한을 검토하세요. 조회 미지원으로 단정하지 않습니다." if managed else
                    "지원되는 설정 범위를 검토하세요." if record["state"] == "unsupported" else
                    "기본 설정 또는 명시 설정이 운영계획에 맞는지 검토하세요."}
    return out


def _target_item(kind, groups, details):
    key, label = _TARGETS[kind]
    values = [details[(row["id"], kind)] for row in groups if (row["id"], kind) in details]
    observed = sum(row["state"] == "observed" for row in values)
    unsupported = len(values)-observed
    missing = len(groups)-len(values)
    defaults = sum(row["state"] == "observed" and row["record_total"] == 0 for row in values)
    state = "unknown" if missing or not groups else "not_applicable" if not observed else "verified"
    item = _item(key, label, state,
        f"광고그룹 {len(groups)}개 중 명시·기본 설정 관측 {observed}개(기본 {defaults}개), 유형상 미지원 {unsupported}개, 자료 미확인 {missing}개입니다.",
        "기본 설정·명시 설정·유형상 미지원은 서로 다릅니다. 계획과 대조하고 미확인 원천부터 확인하세요.")
    if kind == "negative_keywords":
        item["summary"] += " 제외 검색어는 KEYWORD_PLUS_RESTRICT 조회 범위이며 EXP_SEARCH 등 전체 제외 설정의 완결 판정이 아닙니다."
    return item


def _creative_item(entities):
    ads = [row for row in entities.values() if row["entity"] == "ad"]
    linked = sum(row["settings"].get("type") == "ADVOOST_PLACE_AD" and row["settings"].get("ad") == {} for row in ads)
    known = sum(any(_settings(row["settings"]).get(key) for key in ("title", "description", "headline", "text")) or
        row["settings"].get("type") == "ADVOOST_PLACE_AD" and row["settings"].get("ad") == {} for row in ads)
    return _item("creative_copy", "소재 문구·자산", "verified" if ads and known == len(ads) else "unknown",
        f"소재 {len(ads)}개 중 문구 또는 지원 유형의 연결 소재 {known}개(ADVoost 플레이스 연결 소재 {linked}개)를 관측했습니다.",
        "ADVOOST_PLACE_AD의 빈 ad 객체는 정상 연결 형식입니다. 문구 품질·랜딩·전체 자산 완결성은 별도로 검토하세요.")


def _history(observation, now, entities):
    raw = observation.get("history")
    scope = tuple(observation.get(key) for key in ("possibility_id", "customer_id", "stage_revision"))
    if not isinstance(raw, list) or len(raw) > _MAX_ROWS or any(value is None for value in scope):
        return [], 0
    rows = []
    for row in raw:
        if not isinstance(row, Mapping) or tuple(row.get(key) for key in
                ("possibility_id", "customer_id", "stage_revision")) != scope or row.get("execution") != "observed" \
                or row.get("change_kind") not in ("initial", "changed", "removed"):
            continue
        at = _at(row.get("observed_at"))
        entity, identifier = row.get("entity"), row.get("id")
        if at is None or at > now or entity not in set(_ENTITY_LABELS) | {"target:"+key for key in _TARGETS} \
                or not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            continue
        if any(value is not None and (not isinstance(value, str) or not _ID.fullmatch(value))
                for value in (row.get("parent_id"), row.get("campaign_id"))):
            continue
        paths = {**row, "entity": "adgroup" if entity.startswith("target:") else entity}
        detail = {"entity": entity, "id": identifier, "path": _path(paths, entities),
            "observed_at": at.isoformat(), "generation": _generation(row.get("generation")),
            "cycle_day": _text(row.get("cycle_day"), 10), "change_kind": row["change_kind"], "execution": "observed"}
        for key in ("before", "after"):
            value = row.get(key)
            if entity.startswith("target:") and isinstance(value, Mapping):
                records = _target_records(value.get("records"))
                detail[key] = {"state": value.get("state") if value.get("state") in ("observed", "unsupported") else "unknown",
                               "records": records or [], "record_total": len(value["records"]) if records is not None else None}
            else:
                detail[key] = _settings(value) if isinstance(value, Mapping) else None
        rows.append(detail)
    rows.sort(key=lambda row: (row["observed_at"], row["entity"], row["id"]), reverse=True)
    return rows[:_DETAIL_LIMIT], len(rows)


def _entity_details(entities, observation, now, meta):
    performance = observation.get("performance")
    performance = performance if isinstance(performance, Mapping) else {}
    out = []
    for key, entity in sorted(entities.items())[:_DETAIL_LIMIT]:
        raw = entity["settings"]
        described = A.describe(entity["entity"], raw, checked_at=_at(entity["checked_at"]))
        out.append({"entity": entity["entity"], "id": entity["id"], "path": _path(entity, entities),
            "checked_at": entity["checked_at"], "settings": _settings(raw), "status": described["status"],
            "reason": described["reason"], "next_action": "관측 사유와 설정을 운영계획에 대조하세요. 변경·재개를 자동 권고하지 않습니다.",
            "performance": _metric_detail(performance.get(key), now, _at(meta["checked_at"]))})
    return out


def project_setup(*, now, structure=None, campaigns=None, campaign_source=None, plan=None, observation=None):
    """입력을 수정하지 않고 점검 표를 반환한다. 파일·DB·외부 API에 접근하지 않는다.

    plan.goal 및 plan.budget_plan은 별도 운영계획 저장 계약에서 가져온 기록만
    전달한다. 보고서의 서술형 전략/주간·월간 제안을 승인된 목표나 예산으로
    치환하지 않는다. verified는 각 항목에 적힌 관측/기록 범위에만 해당한다.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("점검 기준 시각은 시간대가 있는 시각이어야 합니다")
    structure_meta = _meta(structure, now, structure=True)
    campaign_meta = _meta(campaign_source, now)
    rows = _observations(structure, structure_meta, now)
    campaign_rows = _campaigns(campaigns, campaign_meta)
    shared, entities, targets, details = None, None, {}, None
    if observation is not None:
        # A latest pending/failure is evidence of unavailability, never permission
        # to borrow an older successful structure or campaign snapshot.
        shared = observation if isinstance(observation, Mapping) else {}
        shared_meta = _meta(shared, now)
        shared_meta.update(generation=_generation(shared.get("generation")),
            period_start=_text(shared.get("period_start"), 10), period_end=_text(shared.get("period_end"), 10),
            error_code=_text(shared.get("error_code"), 160))
        entities = _shared_entities(shared, shared_meta, now)
        rows = _shared_reasons(entities) if entities is not None else None
        if rows is None:
            entities = None
            shared_meta["usable"] = False
        campaign_rows = shared.get("campaigns") if entities is not None else None
        structure_meta, campaign_meta = dict(shared_meta), dict(shared_meta)
        targets = _target_details(shared, entities, shared_meta, now) if entities is not None else {}
        history, history_total = _history(shared, now, entities or {})
        details = {"entities": _entity_details(entities, shared, now, shared_meta) if entities is not None else [],
            "entity_total": len(entities or {}), "entities_truncated": len(entities or {}) > _DETAIL_LIMIT,
            "targets": list(targets.values())[:_DETAIL_LIMIT], "target_total": len(targets),
            "targets_truncated": len(targets) > _DETAIL_LIMIT, "history": history, "history_total": history_total,
            "history_truncated": history_total > len(history)}
    if rows is None:
        structure_meta["usable"] = False
    if campaign_rows is None:
        campaign_meta["usable"] = False
    items = [_item("structure", "광고 구조 수집", "verified" if rows is not None else "unknown",
        f"현재 회차의 구조 수집이 완료되어 관측 대상 {len(rows)}개를 확인했습니다. 설정 완결 판정은 아닙니다." if rows is not None else
        "현재 회차의 수집 완결성·확인 시각·상태 원문을 함께 확인하지 못했습니다. 설정 미완료라는 뜻은 아닙니다.",
        "설정 항목별 근거를 이어서 검토하세요." if rows is not None else "구조 수집 상태와 원천 무결성을 확인하세요.")]
    items.extend(_status_item(key, label, codes, rows) for key, label, codes in (
        ("inspection", "심사 상태", _INSPECTION), ("suspension", "중지·삭제 상태", _SUSPENSION),
        ("delivery", "노출 제한 사유", _DELIVERY)))
    budget_proof = B.from_observation(shared, now) if entities is not None else None
    items.extend((_budget_item(campaign_rows, budget_proof, now), _period_item(campaign_rows)))
    if entities is not None:
        groups = [row for row in entities.values() if row["entity"] == "adgroup"]
        items.extend(_target_item(kind, groups, targets) for kind in _TARGETS)
        items.append(_creative_item(entities))
    else:
        for key, label in (("time_targeting", "요일·시간 설정"), ("region_targeting", "지역 설정"),
                       ("age_targeting", "연령 설정"), ("negative_keywords", "제외 검색어"),
                       ("creative_copy", "소재 문구·자산")):
            items.append(_item(key, label, "unknown",
                "현재 회차에 이 설정의 원문을 확인하지 못했습니다. 설정 누락 여부는 미확인입니다.",
                "지원 유형과 실제 설정 원문을 먼저 확인하세요. 전체 시간·전체 지역 설정 자체는 오류가 아닙니다."))
    if entities is not None and not campaign_rows:
        items[0]["summary"] = "현재 회차 조회가 완료되었고 캠페인 0개를 관측했습니다. 광고 안함·비관리·전환 0·태그 정상 판정이 아닙니다."
        items[0]["next_action"] = "계약 관제를 유지하고 계정 연결·광고 유형·조회 권한·신규 세팅·전환 추적을 확인하세요."
    plan = plan if isinstance(plan, Mapping) else {}
    goal = isinstance(plan.get("goal"), str) and 0 < len(plan["goal"].strip()) <= 2000
    budget = isinstance(plan.get("budget_plan"), Mapping) and any(
        _amount(plan["budget_plan"].get(key)) for key in ("daily_budget", "monthly_budget", "total_budget", "amount"))
    items.extend((
        _item("goal", "운영계획 목표 기록", "verified" if goal else "unknown",
              "운영계획에 목표 기록이 있습니다. 승인·집행·달성 확인은 별도입니다." if goal else "연결된 운영계획의 목표 기록이 없습니다.",
              "저장된 목표와 적용 기간을 검토하세요." if goal else "운영계획의 목표를 확인하세요."),
        _item("budget_plan", "운영계획 예산 기록", "verified" if budget else "unknown",
              "운영계획에 예산 기록이 있습니다. 광고 설정·승인·실집행과 대조한 결과는 아닙니다." if budget else
              "연결된 운영계획의 예산 기록이 없습니다.", "운영계획의 예산과 승인 범위를 확인하세요."),
        _item("setup_completeness", "전체 설정 완결성", "unknown",
              "상태 수집 완료와 전체 설정 완료는 다릅니다. 미수집 설정이 있어 전체 완결 여부는 미확인입니다.",
              "미수집 설정 원문과 운영계획을 확인한 뒤 항목별로 검토하세요.")))
    counts = Counter(item["state"] for item in items)
    result = {"version": 1, "items": items, "counts": {state: counts[state] for state in STATES},
            "source": {"kind": "shared_setup_observation" if shared is not None else "stored_observations",
                "structure": structure_meta, "campaigns": campaign_meta,
                "observed_entities": dict(sorted(Counter(row["entity"] for row in rows or []).items())),
                "reason_codes": sorted({row["reason"]["code"] for row in rows or [] if row["reason"]["code"]}),
                "limitations": ["현재 계정·관리 단계·수집 회차의 대조는 호출자가 전달한 freshness에 한합니다.",
                    "미수집 설정과 광고 유형별 미확인 지원 범위를 임의로 정상·누락 판정하지 않습니다.",
                    "실제 광고를 변경하거나 자동 실행·승인 권한을 부여하지 않습니다."]}}
    if shared is not None:
        result["source"]["observation"] = shared_meta
        result["details"] = details
        result["source"]["limitations"].extend([
            "제외 검색어는 KEYWORD_PLUS_RESTRICT 조회 범위입니다. EXP_SEARCH 등 전체 제외 설정의 완결 판정이 아닙니다.",
            "상세 전환은 플랫폼 일반 전환입니다. 구매 완료나 전환 추적 태그의 정상 작동을 보증하지 않습니다.",
            "관측 이력은 실제 설정 변경 실행·승인·복구 완료를 증명하지 않습니다."])
    return result
