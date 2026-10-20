"""설정 관측용 닫힌 필드 계약. HTTP·파일·DB 접근 없이 원문을 검증·축소한다."""
import json
import math
import re
from collections.abc import Mapping

from . import handles as H

MAX_ROWS = 10000
IDS = {"campaign": "nccCampaignId", "adgroup": "nccAdgroupId", "keyword": "nccKeywordId", "ad": "nccAdId"}
PARENTS = {"adgroup": "nccCampaignId", "keyword": "nccAdgroupId", "ad": "nccAdgroupId"}
PREFIXES = {"campaign": "cmp-", "adgroup": "grp-", "keyword": "kwd-", "ad": "nad-"}
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_COMMON = {"customerId", "status", "statusReason", "userLock", "editTm", "regTm", "delFlag"}
_ALLOWED = {
    "campaign": _COMMON | {"nccCampaignId", "name", "campaignTp", "dailyBudget", "useDailyBudget", "usePeriod",
        "periodStartDt", "periodEndDt", "deliveryMethod", "sharedBudgetId", "sharedDailyBudget", "sharedBudgetLock"},
    "adgroup": _COMMON | {"nccAdgroupId", "nccCampaignId", "name", "adgroupType", "bidAmt", "dailyBudget",
        "useDailyBudget", "budgetLock", "sharedBudgetId", "sharedDailyBudget", "sharedBudgetLock", "systemBiddingType",
        "pcNetworkBidWeight", "mobileNetworkBidWeight", "contentsNetworkBidWeight", "contentsNetworkBidAmt",
        "useCntsNetworkBidAmt", "useCntsNetworkBidWeight", "useExpSearch", "aiAdsOptIn", "expSearchBudgetRatio",
        "adRollingType", "adgroupAttrJson"},
    "keyword": _COMMON | {"nccKeywordId", "nccAdgroupId", "nccCampaignId", "keyword", "bidAmt", "useGroupBidAmt", "inspectStatus"},
    "ad": _COMMON | {"nccAdId", "nccAdgroupId", "type", "enable", "inspectStatus", "ad", "adAttr"},
}
_BOOLS = {"userLock", "delFlag", "useDailyBudget", "usePeriod", "sharedBudgetLock", "budgetLock", "useGroupBidAmt",
    "enable", "useCntsNetworkBidAmt", "useCntsNetworkBidWeight", "useExpSearch", "aiAdsOptIn"}
_NUMBERS = {"dailyBudget", "sharedDailyBudget", "bidAmt", "pcNetworkBidWeight", "mobileNetworkBidWeight",
    "contentsNetworkBidWeight", "contentsNetworkBidAmt", "expSearchBudgetRatio"}
_TEXT = {"name", "keyword", "headline", "title", "description", "text"}


def _invalid():
    raise ValueError("설정 원천의 식별·소유·필드 모양을 확인하지 못했습니다")


def valid_id(value, entity=None):
    return isinstance(value, str) and _ID.fullmatch(value) is not None and (
        entity is None or isinstance(entity, str) and entity in PREFIXES and value.startswith(PREFIXES[entity])
        and len(value) > len(PREFIXES[entity]))


def _customer(value, expected):
    try:
        if H.normalize_customer_id(value) != H.normalize_customer_id(expected):
            _invalid()
    except H.NotEligible:
        _invalid()


def _string(value, limit=160):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        _invalid()
    return value


def _amount(value):
    if type(value) not in (int, float) or not 0 <= value <= 10**15 \
            or type(value) is float and not math.isfinite(value):
        _invalid()
    return value


def _object(value, allowed):
    if isinstance(value, str):
        if len(value) > 65536:
            _invalid()
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            _invalid()
    if not isinstance(value, Mapping):
        _invalid()
    kept = {}
    for key in allowed:
        if key not in value:
            continue
        item = value[key]
        if item is None:
            kept[key] = None
        elif key in _BOOLS or key == "useAdvoost":
            if type(item) is not bool:
                _invalid()
            kept[key] = item
        elif key in _NUMBERS:
            kept[key] = _amount(item)
        else:
            kept[key] = _string(item, 2000 if key in _TEXT else 160)
    return kept


def sanitize_record(entity, row, customer_id, parent_id=None):
    if not isinstance(entity, str) or entity not in IDS or not isinstance(row, Mapping) or not valid_id(row.get(IDS[entity]), entity):
        _invalid()
    _customer(row.get("customerId"), customer_id)
    parent = PARENTS.get(entity)
    if parent:
        parent_entity = "campaign" if entity == "adgroup" else "adgroup"
        if not valid_id(parent_id, parent_entity) or row.get(parent) != parent_id:
            _invalid()
    elif parent_id is not None:
        _invalid()
    kept = {}
    for key in _ALLOWED[entity]:
        if key not in row:
            continue
        value = row[key]
        if value is None:
            kept[key] = None
        elif key == "customerId":
            kept[key] = value  # 실제 응답 값 그대로. 없던 고객·부모 필드를 만들지 않는다.
        elif key in IDS.values() or key == "sharedBudgetId":
            if not valid_id(value):
                _invalid()
            kept[key] = value
        elif key in _BOOLS:
            if type(value) is not bool:
                _invalid()
            kept[key] = value
        elif key in _NUMBERS:
            kept[key] = _amount(value)
        elif key == "ad":
            # ADVOOST_PLACE_AD의 {}는 정상 연동형 소재. URL·이미지·사업자 정보는 남기지 않는다.
            kept[key] = _object(value, {"headline", "title", "description", "text"})
        elif key == "adAttr":
            kept[key] = _object(value, {"bidAmt", "useGroupBidAmt"})
        elif key == "adgroupAttrJson":
            kept[key] = _object(value, {"useAdvoost", "contentsType"})
        else:
            kept[key] = _string(value, 2000 if key in _TEXT else 160)
    return kept


def sanitize_criteria(rows, customer_id, group_id, criterion_type):
    if not valid_id(group_id, "adgroup") or criterion_type not in ("SD", "RL", "AG") \
            or not isinstance(rows, list) or len(rows) > MAX_ROWS:
        _invalid()
    _customer(customer_id, customer_id)
    allowed = {"customerId", "ownerId", "dictionaryCode", "codeName", "type", "value", "bidWeight",
               "negative", "enable", "delFlag"}
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("ownerId") != group_id or row.get("type") != criterion_type:
            _invalid()
        _customer(row.get("customerId"), customer_id)
        code = row.get("dictionaryCode")
        if not valid_id(code) or not code.startswith(criterion_type) or code in seen:
            _invalid()
        seen.add(code)
        kept = {}
        for key in allowed:
            if key not in row:
                continue
            value = row[key]
            if value is None:
                kept[key] = None
            elif key == "customerId":
                kept[key] = value
            elif key in ("negative", "enable", "delFlag"):
                if type(value) is not bool:
                    _invalid()
                kept[key] = value
            elif key == "bidWeight":
                kept[key] = _amount(value)
                if not 50 <= value <= 500:
                    _invalid()
            else:
                kept[key] = _string(value, 240 if key == "codeName" else 160)
        out.append(kept)
    return out


def sanitize_negative(rows, customer_id, group_id):
    """공식 응답에는 customerId/ownerId가 없다. parent endpoint + X-Customer 범위의 관측이다.

    nccAdgroupId는 실제 응답에서 필수로 대조한다. 예상 밖 소유 필드가 있으면
    대조하되 없던 고객·부모 필드를 만들어 독립 소유 근거처럼 저장하지 않는다.
    """
    if not valid_id(group_id, "adgroup") or not isinstance(rows, list) or len(rows) > MAX_ROWS:
        _invalid()
    _customer(customer_id, customer_id)
    allowed = {"nccAdgroupId", "nccAdgroupRestrictKwdId", "keyword", "description", "type", "regTm", "delFlag"}
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("nccAdgroupId") != group_id:
            _invalid()
        if "customerId" in row:
            _customer(row["customerId"], customer_id)
        if "ownerId" in row and row["ownerId"] != group_id:
            _invalid()
        identifier = row.get("nccAdgroupRestrictKwdId")
        if not valid_id(identifier) or identifier in seen or not isinstance(row.get("keyword"), str) or not row["keyword"]:
            _invalid()
        if "type" in row and row["type"] != "KEYWORD_PLUS_RESTRICT":
            _invalid()
        seen.add(identifier)
        kept = {}
        for key in allowed:
            if key not in row:
                continue
            value = row[key]
            if value is None and key in ("description", "regTm"):
                kept[key] = None
            elif key == "delFlag":
                if type(value) is not bool:
                    _invalid()
                kept[key] = value
            else:
                kept[key] = _string(value, 2000 if key in ("keyword", "description") else 160)
        out.append(kept)
    return out


def valid_target_constraints(rows, group_type, criterion_type):
    """검증·축소한 타겟의 알려진 유형 제약만 대조한다. 지원 여부의 근거는 아니다.

    쇼핑 지역 타겟은 공식 2023-10-18 명세상 제외(true)·가중치100만 지원한다.
    빈 목록은 명시적 타겟이 없는 관측이며, 다른 유형의 제약은 추측하지 않는다.
    """
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(row, Mapping) for row in rows):
        return False
    if group_type in ("SHOPPING", "CATALOG", "SHOPPING_BRAND") and criterion_type == "RL":
        return all(row.get("negative") is True and type(row.get("bidWeight")) in (int, float)
                   and row["bidWeight"] == 100 for row in rows)
    return True


def capabilities(group_type):
    """네이버 공식 유형별 조회 대상. 미확인 유형·제외어 지원을 추측하지 않는다.

    2023-08-23 타겟 표 + 2023-10-18 쇼핑 지역 제외 추가를 반영한다.
    제외어 GET의 현행 명세는 WEB_SITE / KEYWORD_PLUS_RESTRICT만 명시한다.
    ADVoost의 수동 변경 제한은 조회 미지원과 다르므로 별도 진단한다.
    """
    result = dict.fromkeys(("SD", "RL", "AG", "negative_keywords"), "unknown")
    if group_type in ("WEB_SITE", "SHOPPING", "CATALOG", "SHOPPING_BRAND", "INFORMATION", "PRODUCT", "LOCAL_AD"):
        result.update(SD="supported", RL="supported", AG="supported")
    elif group_type == "PLACE":
        result.update(SD="supported", RL="supported", AG="unsupported")
    elif group_type in ("BRAND_SEARCH", "BRAND_ZONE"):
        result.update(SD="unsupported", RL="unsupported", AG="unsupported")
    if group_type == "WEB_SITE":
        result["negative_keywords"] = "supported"
    return result
