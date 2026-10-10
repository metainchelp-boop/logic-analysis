"""새 전략·계획의 판 관리. SQL·외부 호출·광고 실행을 포함하지 않는다."""
from copy import deepcopy
from datetime import datetime
import json
import math
import re

from . import marketing_strategy as STR, store as S

MAX_CHARS = 24000
MAX_VERSION = 2**53-1
PLAN_FIELDS = frozenset({"goal", "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap", "notes"})
GOALS = frozenset({"impressions", "clicks", "cpa", "roas"})
AUTO_STAGES = frozenset({"진행중", "전략관리", "재계약진행중"})
EDIT_STAGES = AUTO_STAGES | {"사후관리", "홀딩", "홀딩중"}
PROVIDER_STATUS = {"configured": False, "state": "not_enabled", "reason": "API 연결과 비용 한도 확인 전", "paid_calls": 0}
POLICY = {"execution_enabled": False, "automatic_changes": ["bid"],
          "single_increase_percent": 10, "single_decrease_percent": 15,
          "rolling_day_increase_percent": 30, "rolling_day_decrease_percent": 40,
          "weekly_increase_requires_approval_percent": 50,
          "new_campaign_requires_approval": True, "native_auto_bid_read_only": True}


def version(value):
    if type(value) is not int or not 0 <= value <= MAX_VERSION:
        raise S.StoreRefused("문서 판을 확인해 주세요")
    return value


def strategy_document(value):
    try:
        return STR.normalize_document(value)
    except STR.StrategyRefused:
        raise S.StoreRefused("전략 문안의 항목과 길이를 확인해 주세요") from None


def plan_document(value, *, approve=False):
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS:
        raise S.StoreRefused("자동화 계획 항목을 확인해 주세요")
    clean = dict(value)
    if clean["goal"] is not None and (not isinstance(clean["goal"], str) or clean["goal"] not in GOALS):
        raise S.StoreRefused("목표 지표를 확인해 주세요")
    for key in ("target_value", "daily_spend_cap", "absolute_bid_cap", "loss_cap"):
        item = clean[key]
        if item is not None and (type(item) not in (int, float) or not 0 < item <= 10**12 or not math.isfinite(item)):
            raise S.StoreRefused("목표와 한도는 유한한 양수로 입력해 주세요")
    days = clean["experiment_days"]
    if days is not None and (type(days) is not int or not 2 <= days <= 30):
        raise S.StoreRefused("실험 기간은 2~30일로 입력해 주세요")
    notes = clean["notes"]
    if (not isinstance(notes, str) or len(notes) > 1000 or re.search(r"[<>\x00-\x09\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", notes)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in notes)):
        raise S.StoreRefused("계획 메모를 일반 텍스트 1000자 이내로 입력해 주세요")
    clean["notes"] = notes.strip()
    if approve and (any(clean[key] is None for key in PLAN_FIELDS - {"notes"})
                    or clean["loss_cap"] > clean["daily_spend_cap"] * days):
        raise S.StoreRefused("목표·기간·예산·입찰·손실 한도를 모두 확인한 뒤 승인해 주세요")
    return clean


def empty_plan():
    return {key: "" if key == "notes" else None for key in PLAN_FIELDS}


def cap_raise(current, approved):
    if approved["state"] != "approved":
        return False
    return any(current["document"][key] is not None and current["document"][key] > approved["document"][key]
               for key in ("daily_spend_cap", "absolute_bid_cap", "loss_cap"))


def head_key(kind, identity):
    return kind + "-head:" + identity


def history_key(kind, identity, v):
    return kind + "-version:" + identity + f":{v:016d}"


def empty(metadata, document=None):
    return {"version": 0, "state": "empty", "metadata": deepcopy(metadata), "document": document,
            "source": None, "author": None, "approved_by": None, "approved_at": None}


def _actor(value):
    from app.naver_auto import scope as SC
    return SC.is_person_idx(value)


def _at(value):
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except (ValueError, TypeError):
        return False


def decode(row, metadata, kind):
    if row is None:
        return empty(metadata, empty_plan() if kind == "automation-plan" else None)
    try:
        if type(row[0]) is not int or not 0 < row[0] <= MAX_CHARS or row[0] != len(row[1]):
            raise ValueError()
        record = json.loads(row[1])
        if (set(record) != {"version", "state", "metadata", "document", "source", "author", "approved_by", "approved_at"}
                or version(record["version"]) == 0 or record["metadata"] != metadata
                or record["state"] not in ("draft", "approved") or record["source"] not in ("rule_based", "staff", "claude")
                or not isinstance(record["author"], dict) or set(record["author"]) != {"actor", "at"}
                or not _actor(record["author"]["actor"]) or not _at(record["author"]["at"])):
            raise ValueError()
        clean = plan_document(record["document"], approve=record["state"] == "approved") if kind == "automation-plan" else strategy_document(record["document"])
        if clean != record["document"]:
            raise ValueError()
        if record["state"] == "approved":
            if not _actor(record["approved_by"]) or not _at(record["approved_at"]):
                raise ValueError()
        elif record["approved_by"] is not None or record["approved_at"] is not None:
            raise ValueError()
        return record
    except (ValueError, TypeError, KeyError, S.StoreRefused):
        raise S.StoreError("저장된 승인 문서를 확인해 주세요") from None


def present(record, *, plan=False):
    out = deepcopy(record)
    if plan:
        out["plan"] = out.pop("document")
        out.update(execution_status="not_enabled", experiment_results=None)
    else:
        out["shared"] = ({key: deepcopy(record[key]) for key in
            ("version", "state", "metadata", "document", "source", "approved_at")} if record["state"] == "approved" else None)
        out["provider_status"] = dict(PROVIDER_STATUS)
    return out
