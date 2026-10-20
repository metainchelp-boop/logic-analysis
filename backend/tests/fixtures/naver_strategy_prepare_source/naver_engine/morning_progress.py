"""연속 상세점검의 한 계정 진행자료. 원장이 아닌 유한한 재사용 슬롯이다.

완료된 HTTP 응답 하나씩만 저장한다. 날짜/귀속/판정 입력 변경과 실제 통신 실패는
이어 읽지 않으며, 내부 호출 예산 중단만 다음 회차로 넘긴다. 비밀값/이름/URL은 없다.
"""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math

MAX_CAMPAIGNS = 10_000
MAX_BYTES = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024
MAX_SUMMARY_SLOTS = 100
FIELDS = ("impCnt", "clkCnt", "salesAmt", "ccnt")


class ProgressLimit(Exception):
    pass


class ProgressCorrupt(Exception):
    pass


def packed(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def campaign_fingerprint(infos):
    # CampaignInfo에는 판정 입력만 있다. 정렬로 원천의 순서 변경은 무시한다.
    return digest(packed([asdict(c) for c in sorted(infos, key=lambda c: c.campaign_id)]))


def payload_body(kind, slot, value):
    limit = MAX_SUMMARY_SLOTS if kind == "summary" else MAX_CAMPAIGNS if kind == "daily" else 0
    if type(slot) is not int or not 0 <= slot < limit or not isinstance(value, dict) \
            or set(value) != {"ids", "rows", "cycle"}:
        raise ProgressCorrupt()
    ids, rows, cycle = value["ids"], value["rows"], value["cycle"]
    from . import naver_read as N
    if not isinstance(ids, list) or not 1 <= len(ids) <= (100 if kind == "summary" else 1) \
            or any(not isinstance(i, str) or not N._CAMPAIGN_ID.fullmatch(i) for i in ids) \
            or len(set(ids)) != len(ids) or not isinstance(rows, dict):
        raise ProgressCorrupt()
    if cycle is not None:
        try:
            if not isinstance(cycle, str) or datetime.fromisoformat(cycle).tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProgressCorrupt() from None
    if kind == "summary" and not set(rows).issubset(ids):
        raise ProgressCorrupt()
    if kind == "daily" and len(rows) > 29:
        raise ProgressCorrupt()
    for row in rows.values():
        if not isinstance(row, dict) or set(row) != set(FIELDS) or any(
                v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in row.values()):
            raise ProgressCorrupt()
    body = packed(value)
    if len(body.encode("utf-8")) > MAX_CHUNK_BYTES:
        raise ProgressLimit()
    return body


class Progress:
    """저장 경계를 감싼 한 회차 객체. 전체 payload를 매 요청 다시 직렬화하지 않는다."""
    def __init__(self, store, customer_id, possibility_id, day, clock):
        self.store, self.cid, self.pid, self.day, self.clock = store, customer_id, possibility_id, day, clock
        self.saved = store.morning_progress(customer_id, possibility_id, day, clock())
        self.generation = self.saved["generation"] if self.saved else None
        self.fingerprint = None
        self.chunks = {}
        if self.saved and self.saved["status"] == "blocked" and clock() < datetime.fromisoformat(self.saved["next_try_at"]):
            raise ProgressLimit()

    def begin(self, infos):
        self.fingerprint = campaign_fingerprint(infos)
        saved = self.store.begin_morning_progress(self.cid, self.pid, self.day, self.fingerprint, self.clock())
        self.generation, self.chunks = saved["generation"], saved["chunks"]
        if len(infos) > MAX_CAMPAIGNS:
            self.discard(blocked=True)
            raise ProgressLimit()

    def fetch(self, kind, slot, ids, fetch, want):
        saved = self.chunks.get((kind, slot))
        if saved is None:
            result = fetch()
            rows = result.rows if kind == "summary" else result.days
            value = {"ids": list(ids), "rows": rows,
                     "cycle": None if result.cycle_base_tm is None else result.cycle_base_tm.isoformat()}
            self.store.record_morning_progress(self.cid, self.generation, kind, slot, value, self.clock())
        else:
            body, checksum = saved
            if not isinstance(body, str) or digest(body) != checksum:
                raise ProgressCorrupt()
            try:
                value = json.loads(body)
            except (ValueError, TypeError):
                raise ProgressCorrupt() from None
            payload_body(kind, slot, value)
        if value["ids"] != list(ids) or (kind == "daily" and not set(value["rows"]).issubset(d.isoformat() for d in want)):
            raise ProgressCorrupt()
        cycle = None if value["cycle"] is None else datetime.fromisoformat(value["cycle"])
        if cycle is not None and cycle > self.clock():
            raise ProgressCorrupt()
        return value["rows"], cycle

    def discard(self, *, blocked=False):
        if self.generation is not None:
            self.store.finish_morning_progress(self.cid, self.generation, self.clock(), blocked=blocked)


def read_stats(reader, ah, infos, today, clock, deadline, progress):
    from . import morning as M
    since, until, want = M.window(today)
    ordered = sorted(infos, key=lambda c: c.campaign_id)
    progress.begin(ordered)
    summary, cycles, series = {}, [], {}
    for start in range(0, len(ordered), 100):
        M._check_deadline(clock, deadline)
        ids = [c.campaign_id for c in ordered[start:start+100]]
        rows, cycle = progress.fetch("summary", start // 100, ids,
            lambda: reader.get_stats_summary(ah, ids, since, until, fields=FIELDS), want)
        summary.update(rows)
        cycles.append(cycle)
    zero = {d: {f: 0 for f in FIELDS} for d in want}
    for index, c in enumerate(ordered):
        row = summary.get(c.campaign_id)
        if (row is None and not M._running(c)) or (row is not None and all(M._known(row.get(f)) and row[f] == 0 for f in FIELDS)):
            series[c.campaign_id] = {d: dict(v) for d, v in zero.items()}
            continue
        M._check_deadline(clock, deadline)
        rows, cycle = progress.fetch("daily", index, [c.campaign_id],
            lambda: reader.get_stats_daily(ah, c.campaign_id, since, until, fields=FIELDS), want)
        cycles.append(cycle)
        series[c.campaign_id] = M.reconcile(rows, row, want)
    # 최종 확인도 예산에 포함한다. 이 직전에 잘려도 위의 완료 조각은 남는다.
    M._check_deadline(clock, deadline)
    latest = M._campaign_infos(reader.get_campaigns(ah), progress.cid)
    if latest is None or campaign_fingerprint(latest) != progress.fingerprint:
        from . import handles as H
        raise H.HandleInvalid("morning-campaigns-changed")
    return series, M.complete_through(cycles) if ordered else until
