"""저장된 광고 상태와 계획 기록만 읽는 순수 세팅 점검 projection.

``structure``는 Store.structure_checks()[customer_id]의 결과다. ``ok``는
구조 수집의 완결성만 뜻하며 광고 설정이나 운영의 적정성을 보증하지 않는다.
캠페인 원문을 연결할 때는 campaigns_json과 함께 campaign_source의
status='ok', complete=True, stale=False, checked_at을 제공해야 한다.
stale=False는 호출자가 현재 계정·관리 단계·수집 회차를 대조한 결과여야 한다.
이 모듈은 계정 권한을 발급하거나 원천을 수집하지 않는다.
"""
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timedelta
import math
import re

from . import ad_reasons as A


STATES = ("attention", "unknown", "verified", "not_applicable")
_MAX_ROWS = 10000
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
            ("ok", "pending", "reading", "partial", "retry", "limited", "reauth_required") else "unknown",
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


def _budget_item(rows):
    if rows:
        counts = Counter()
        for row in rows:
            shared = row.get("sharedBudgetId")
            if isinstance(shared, str) and shared:
                if not _amount(row.get("sharedDailyBudget")):
                    break
                counts["shared"] += 1
            elif row.get("useDailyBudget") is False:
                counts["unused"] += 1
            elif row.get("useDailyBudget") is True and _amount(row.get("dailyBudget")):
                counts["daily"] += 1
            else:
                break
        else:
            return _item("campaign_budget", "캠페인 예산 설정", "verified",
                f"일예산 사용 {counts['daily']}개 · 일예산 미사용 {counts['unused']}개 · 공유예산 {counts['shared']}개를 관측했습니다.",
                "일예산 미사용 자체는 오류가 아닙니다. 계획 대비 적정 금액·승인·실집행은 별도 확인하세요.")
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


def project_setup(*, now, structure=None, campaigns=None, campaign_source=None, plan=None):
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
    items.extend((_budget_item(campaign_rows), _period_item(campaign_rows)))
    for key, label in (("time_targeting", "요일·시간 설정"), ("region_targeting", "지역 설정"),
                       ("age_targeting", "연령 설정"), ("negative_keywords", "제외 검색어"),
                       ("creative_copy", "소재 문구·자산")):
        # 공식 타겟 지원 표(2022-04-26): SHOPPING의 지역 타겟은 미지원.
        unsupported = key == "region_targeting" and campaign_rows and \
            all(row.get("campaignTp") == "SHOPPING" for row in campaign_rows)
        items.append(_item(key, label, "not_applicable" if unsupported else "unknown",
            "확인된 전체 캠페인이 SHOPPING 유형이므로 지역 타겟 설정은 적용 대상이 아닙니다." if unsupported else
            "현행 저장 구조에 이 설정의 원문이 수집되어 있지 않습니다. 설정 누락 여부는 미확인입니다.",
            "해당 광고 유형의 지원 범위 안에서 운영하세요." if unsupported else
            "지원 유형과 실제 설정 원문을 먼저 확인하세요. 전체 시간·전체 지역 설정 자체는 오류가 아닙니다."))
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
    return {"version": 1, "items": items, "counts": {state: counts[state] for state in STATES},
            "source": {"kind": "stored_observations",
                "structure": structure_meta, "campaigns": campaign_meta,
                "observed_entities": dict(sorted(Counter(row["entity"] for row in rows or []).items())),
                "reason_codes": sorted({row["reason"]["code"] for row in rows or [] if row["reason"]["code"]}),
                "limitations": ["현재 계정·관리 단계·수집 회차의 대조는 호출자가 전달한 freshness에 한합니다.",
                    "미수집 설정과 광고 유형별 미확인 지원 범위를 임의로 정상·누락 판정하지 않습니다.",
                    "실제 광고를 변경하거나 자동 실행·승인 권한을 부여하지 않습니다."]}}
