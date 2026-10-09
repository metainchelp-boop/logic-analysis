"""불변 수치판에 묶인 별도 문안 판. 내부 조회는 호출자가 현재 권한을 먼저 확인한다.

기존 meta의 전용 namespace만 쓴다. 원본 보고서·검토 사유와 schema11은 변경하지 않는다.
공유 투영은 지금 문안 판이 승인됐을 때만 만들며 내부 메모와 광고주 요청 기록을 싣지 않는다.
"""
from copy import deepcopy
from datetime import date, datetime
import json
import math
import re

from . import management as MG, report_views as RV, reporting as R, store as S
from app.naver_auto import org_snapshot as O, scope as SC


MAX_VERSION = 2**53 - 1
MAX_RECORD_CHARS = 16000
TEXT_LIMITS = {"internal_note": 1000, "client_feedback": 1000,
               "shared_comment": 2000, "next_plan": 1000}
TARGET_FIELDS = frozenset({"cpa", "roas", "spend_per_day", "source"})
DOCUMENT_FIELDS = frozenset(TEXT_LIMITS) | {"plan_due", "targets"}
TARGET_UNITS = {"cpa": "KRW/conversion", "roas": "percent", "spend_per_day": "KRW/day"}


class NotesConflict(S.StoreRefused):
    """다른 문안 판을 덮어쓰지 않도록 부르는 쪽에 새 조회를 요구한다."""


def _identity(report_id, account_key, fingerprint):
    S._pos_int(report_id, "보고서")
    if not isinstance(account_key, str) or (account_key != "company" and
            not re.fullmatch(r"[0-9a-f]{64}", account_key)):
        raise S.StoreRefused("보고 범위를 확인해 주세요")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise S.StoreRefused("보고서 판을 확인해 주세요")


def _version(value, *, allow_zero=True):
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= MAX_VERSION:
        raise S.StoreRefused("문안 판 번호를 확인해 주세요")
    return value


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit or any(
            ord(char) < 32 and char not in "\n\t" or 0x7f <= ord(char) <= 0x9f or
            0xd800 <= ord(char) <= 0xdfff or char in "<>" for char in value):
        raise S.StoreRefused("문안은 제한 길이의 일반 텍스트로 입력해 주세요")
    return value.strip()


def _document(value):
    if not isinstance(value, dict) or set(value) - DOCUMENT_FIELDS:
        raise S.StoreRefused("문안 입력 항목을 확인해 주세요")
    document = {key: _text(value.get(key, ""), limit) for key, limit in TEXT_LIMITS.items()}
    due = value.get("plan_due")
    if due is not None:
        try:
            if not isinstance(due, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", due):
                raise ValueError()
            date.fromisoformat(due)
        except ValueError:
            raise S.StoreRefused("계획 기한은 YYYY-MM-DD 날짜로 입력해 주세요") from None
    document["plan_due"] = due
    targets = value.get("targets", {})
    if not isinstance(targets, dict) or set(targets) - TARGET_FIELDS:
        raise S.StoreRefused("목표 입력 항목을 확인해 주세요")
    clean = {"source": _text(targets.get("source", ""), 500)}
    for key in TARGET_UNITS:
        number = targets.get(key)
        try:
            valid = number is None or (type(number) in (int, float) and 0 <= number <= 2**53-1 and math.isfinite(number))
        except OverflowError:
            valid = False
        if not valid:
            raise S.StoreRefused("목표는 0 이상의 유한한 숫자로 입력해 주세요")
        clean[key] = number
    if any(clean[key] is not None for key in TARGET_UNITS) and not clean["source"]:
        raise S.StoreRefused("목표값의 출처와 합의 근거를 입력해 주세요")
    document["targets"] = clean
    return document


def _scope(row, report_id, account_key, fingerprint):
    if row is None or row[2] != fingerprint:
        raise S.StoreRefused("보고서가 변경되었습니다. 해당 판을 다시 확인해 주세요")
    try:
        payload = json.loads(row[3])
        saved = payload["period"]
        period = R.period(saved["kind"], date.fromisoformat(saved["start"]))
        if (period.key != row[1] or payload.get("period_key") != row[1] or
                saved["end"] != str(period.end) or payload.get("revision_fingerprint") != fingerprint):
            raise ValueError()
        if account_key != "company":
            selected = RV._account_payload(payload, account_key)
            if not isinstance(selected, dict) or selected.get("period") != saved or selected.get("period_key") != row[1]:
                raise ValueError()
        metadata = {"report_id": report_id, "account_key": account_key,
                    "revision_fingerprint": fingerprint,
                    "period": {key: saved[key] for key in ("kind", "start", "end")},
                    "target_units": dict(TARGET_UNITS)}
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise S.StoreRefused("저장된 보고 기간과 계정 범위를 확인해 주세요") from None
    return row[0], row[1], metadata


def _prefix(report_id, account_key):
    return f"{report_id}:{account_key}"


def _head_key(report_id, account_key):
    return "report-notes-head:" + _prefix(report_id, account_key)


def _version_prefix(report_id, account_key):
    return "report-notes-version:" + _prefix(report_id, account_key) + ":"


def _empty(metadata):
    return {"version": 0, "state": "empty", "metadata": metadata, "document": _document({}),
            "author": None, "approved_by": None, "approved_at": None, "shared": None}


def _decode(raw, length, metadata):
    if length > MAX_RECORD_CHARS:
        raise S.StoreError("저장된 문안 길이 제한을 초과했습니다")
    try:
        item = json.loads(raw)
        _version(item["version"], allow_zero=False)
        if item["state"] not in ("draft", "approved") or item["metadata"] != metadata:
            raise ValueError()
        if _document(item["document"]) != item["document"]:
            raise ValueError()
        author = item["author"]
        if not isinstance(author, dict) or set(author) != {"actor", "at"} or not SC.is_person_idx(author["actor"]):
            raise ValueError()
        if datetime.fromisoformat(author["at"]).tzinfo is None:
            raise ValueError()
        if item["state"] == "approved":
            if not SC.is_person_idx(item["approved_by"]) or datetime.fromisoformat(item["approved_at"]).tzinfo is None:
                raise ValueError()
        elif item["approved_by"] is not None or item["approved_at"] is not None:
            raise ValueError()
    except (KeyError, TypeError, ValueError, S.StoreRefused, OverflowError):
        raise S.StoreError("저장된 문안 판을 읽지 못했습니다") from None
    return item


def _head(row, metadata):
    return _empty(metadata) if row is None else _decode(row[1], row[0], metadata)


def shared_projection(notes):
    """호출자가 받은 내부 문서에서 승인된 공유 필드만 명시적으로 고른다."""
    if notes["state"] != "approved":
        return None
    document = notes["document"]
    return deepcopy({**{key: notes[key] for key in ("version", "state", "metadata", "author",
                                                  "approved_by", "approved_at")},
                     **{key: document[key] for key in ("shared_comment", "next_plan", "plan_due", "targets")}})


def _present(notes):
    out = deepcopy(notes)
    out["shared"] = shared_projection(notes)
    return out


def history_query(report_id, account_key, revision_fingerprint, *, before_version=None, limit=20):
    _identity(report_id, account_key, revision_fingerprint)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise S.StoreRefused("문안 이력은 1~20개씩 조회합니다")
    if before_version is not None:
        _version(before_version, allow_zero=False)
    prefix = _version_prefix(report_id, account_key)
    end = prefix + (f"{before_version:016d}" if before_version is not None else "~")
    return prefix, end


def history(rows, prefix, metadata, limit):
    items = []
    for key, length, raw in rows[:limit]:
        item = _decode(raw, length, metadata)
        if key != prefix + f"{item['version']:016d}":
            raise S.StoreError("저장된 문안 이력 판이 일치하지 않습니다")
        items.append(item)
    return {"items": items, "next_before_version": items[-1]["version"] if len(rows) > limit else None}


def _require_actor(store, pid, actor, now):
    from . import inventory as I, sync as Y
    if not SC.is_person_idx(actor):
        raise S.StoreRefused("문안 작성자를 확인해 주세요")
    S._report_require_scope(store, pid, actor, now, SC.ACT_APPROVE)
    if not O.allows_raising(Y.org_freshness(store, now)):
        raise S.StoreRefused("최신 조직 권한을 확인한 뒤 문안을 저장해 주세요")
    catalog, state = I.catalog_status(store, now)
    company = next((row for row in catalog["items"] if row["possibility_id"] == pid), None) if catalog else None
    if state != "accepted" or company is None or "".join((company["stage"] or "").split()) not in MG.DAILY_STAGES:
        raise S.StoreRefused("현재 관리 중인 업체의 문안만 저장할 수 있습니다")
