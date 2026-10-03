"""현재 권한으로 만든 화면 응답의 선택적 변경분 전송. DB·네트워크 접근 없음."""
import secrets
import json
import hashlib
import time
import threading
from collections import OrderedDict
from datetime import date, datetime


PATHS = frozenset({"/accounts", "/board", "/dashboard", "/reports"})
KEY_FIELDS = {"/accounts": ("ad_account_no",), "/board": ("possibility_id",),
              "/reports": ("possibility_id", "period_key")}
RESPONSE_MAX_BYTES = 4 * 1024 * 1024


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def context_key(value):
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        raise TypeError("화면 범위 자료형이 올바르지 않습니다")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=encode)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _indexed(payload, fields):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        values = [row.get(field) for field in fields]
        if any(not ((type(value) is str and value) or
                    (type(value) is int and 0 < value <= 9007199254740991)) for value in values):
            return None
        key = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        if key in result:
            return None
        result[key] = row
    return result


class ViewSync:
    """128개·직렬화 총 16MiB·300초 상한. 토큰/DB 연결은 저장하지 않는다."""
    def __init__(self, *, ttl=300, max_entries=128, max_bytes=16 * 1024 * 1024, monotonic=None):
        self._snapshots = OrderedDict()
        self._ttl, self._monotonic = ttl, monotonic or time.monotonic
        self._max_entries, self._max_bytes = max_entries, max_bytes
        self._bytes = 0
        self._lock = threading.Lock()

    def _remove(self, view_cursor):
        _, raw = self._snapshots.pop(view_cursor)
        self._bytes -= len(raw) + len(view_cursor)

    def _prune(self, tick):
        for view_cursor, (expires, _) in list(self._snapshots.items()):
            if expires <= tick:
                self._remove(view_cursor)

    def respond(self, path, payload, *, context, view_cursor, now):
        raw = _encoded([context, path, payload])
        fields = KEY_FIELDS.get(path)
        valid_keys = not fields or _indexed(payload, fields) is not None
        tick = self._monotonic()
        with self._lock:
            self._prune(tick)
            entry = self._snapshots.get(view_cursor)
            if entry is not None:
                self._snapshots.move_to_end(view_cursor)
        previous = None if entry is None else json.loads(entry[1])
        if valid_keys and entry is not None and entry[1] == raw:
            return {"version": 1, "mode": "unchanged", "cursor": view_cursor,
                    "base_cursor": view_cursor, "checked_at": now.isoformat(), "data": None, "rows": None}
        next_cursor = secrets.token_urlsafe(24)
        retain = valid_keys and len(raw) + len(next_cursor) <= self._max_bytes
        response = {"version": 1, "mode": "full", "cursor": next_cursor,
                "base_cursor": None, "checked_at": now.isoformat(), "data": payload, "rows": None}
        if not retain:
            response["cursor"] = None
        if retain and previous is not None and previous[:2] == [context, path]:
            if fields:
                before, after = _indexed(previous[2], fields), _indexed(payload, fields)
                if before is not None and after is not None:
                    response.update(mode="delta", base_cursor=view_cursor, data={k: v for k, v in payload.items() if k != "rows"},
                        rows={"key_fields": list(fields), "upsert": [row for key, row in after.items()
                              if key not in before or _encoded(before[key]) != _encoded(row)],
                              "removed": [key for key in before if key not in after], "order": list(after)})
            elif path == "/dashboard":
                response.update(mode="delta", base_cursor=view_cursor)
        if len(_encoded(response)) > RESPONSE_MAX_BYTES:
            response.update(mode="full", base_cursor=None, data=payload, rows=None)
            if len(_encoded(response)) > RESPONSE_MAX_BYTES:
                # 껍질만으로 기존 정상 응답을 중계 한도 밖으로 밀지 않는다.
                # 원본 자체가 한도를 넘는 경우는 기존 중계의 거절을 그대로 받는다.
                return payload
        if retain:
            with self._lock:
                self._prune(self._monotonic())
                self._snapshots[next_cursor] = (tick+self._ttl, raw)
                self._bytes += len(raw) + len(next_cursor)
                while len(self._snapshots) > self._max_entries or self._bytes > self._max_bytes:
                    self._remove(next(iter(self._snapshots)))
        return response
