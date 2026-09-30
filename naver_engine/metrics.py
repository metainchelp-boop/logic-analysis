"""G1~G3 공유 성과 — 아침 29일 비교와 분리한 30일 완결 자료만 보낸다.

오늘의 최신 수락 짝 전체를 고정하고, 가망마다 모든 계정·캠페인·30일·네 지표를
읽는다. 빈 목록/모르는 값/늦은 자료는 0이 아니다. 합계와 일별의 정수 합이
정확히 같을 때만 빠진 일별 칸을 0으로 증명한다. 결과는 저장소에 먼저 고정하고
같은 자료를 재전송한다. 고객·캠페인 번호와 이름은 전산 요청에 들어가지 않는다.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from time import monotonic

from . import erp_alert as EA
from . import handles as H
from . import naver_read as N
from . import store as S

FIELDS = ("impCnt", "clkCnt", "salesAmt", "ccnt")
OUTPUT_FIELDS = ("impressions", "clicks", "spend", "conversions")
MAX_NUMBER = 9007199254740991
WINDOW_DAYS = 30
START = time(8, 10)
END = time(18, 0)
MAX_CALLS = 80
MAX_CAMPAIGNS = 5000
BACKOFF_MINUTES = (2, 5, 15, 30)


class MetricsIncomplete(ValueError):
    """자료가 완결되지 않았다. 예외에는 원천 번호·이름·숫자를 담지 않는다."""


class _BudgetExpired(Exception):
    pass


@dataclass(frozen=True)
class MetricsOutcome:
    code: str
    counts: dict = field(default_factory=dict)


def window(today: date):
    if type(today) is not date:
        raise MetricsIncomplete("날짜 모양이 아닙니다")
    end = today - timedelta(days=1)
    start = today - timedelta(days=WINDOW_DAYS)
    return start, end, tuple(start + timedelta(days=n) for n in range(WINDOW_DAYS))


def number(value):
    # 네이버가 정수값을 실수 모양으로 보내도 정확한 정수만 받는다. 소수는 반올림하지 않는다.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > MAX_NUMBER \
            or not math.isfinite(value) or int(value) != value:
        raise MetricsIncomplete("완결된 정수 지표가 아닙니다")
    return int(value)


def _cycle(raw, today, now):
    try:
        value = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if not isinstance(value, datetime) or value.tzinfo is None \
                or value < datetime.combine(today, time(), tzinfo=S.KST) or value > now + S.FUTURE_SLACK:
            raise ValueError()
        return value
    except (TypeError, ValueError):
        raise MetricsIncomplete("자료 기준 시각이 완결되지 않았습니다") from None


def reconcile(source, summary, today):
    """정확한 같은 30일 합계로만 빈 칸을 0으로 증명한다. 알려진 합계 불일치도 거절한다."""
    if not isinstance(source, dict) or not isinstance(summary, dict) or set(summary) != set(FIELDS):
        raise MetricsIncomplete("지표 모양이 아닙니다")
    wanted = {d.isoformat() for d in window(today)[2]}
    if set(source) - wanted:
        raise MetricsIncomplete("기간 밖 자료가 있습니다")
    out = {d: {} for d in sorted(wanted)}
    for d in out:
        row = source.get(d)
        if row is not None and (not isinstance(row, dict) or set(row) != set(FIELDS)):
            raise MetricsIncomplete("하루 지표 모양이 아닙니다")
        for name in FIELDS:
            value = None if row is None else row.get(name)
            out[d][name] = None if value is None else number(value)
    for name in FIELDS:
        total = number(summary[name])
        known = sum(row[name] for row in out.values() if row[name] is not None)
        if known != total:
            raise MetricsIncomplete("기간 합계와 하루별 지표가 다릅니다")
        for row in out.values():
            if row[name] is None:
                row[name] = 0
    return out


def aggregate(possibility_id, expected_customers, accounts, today, now):
    """보관할 원천 스냅샷을 다시 검사해 최소 전송 본문을 만든다. 저장소에서도 호출한다."""
    if type(possibility_id) is not int or not 0 < possibility_id < 10 ** 15:
        raise MetricsIncomplete("가망 번호 모양이 아닙니다")
    if not isinstance(now, datetime) or now.tzinfo is None or now.astimezone(S.KST).date() != today:
        raise MetricsIncomplete("자료 날짜가 달라졌습니다")
    expected = set(expected_customers)
    if not expected or len(expected) != len(expected_customers) or any(type(cid) is not int or cid <= 0 for cid in expected):
        raise MetricsIncomplete("계정 목록이 완결되지 않았습니다")
    if not isinstance(accounts, (list, tuple)) or len(accounts) != len(expected):
        raise MetricsIncomplete("전체 계정 자료가 아닙니다")
    seen, campaigns_seen = set(), set()
    totals = dict.fromkeys(FIELDS, 0)
    for account in accounts:
        if not isinstance(account, dict) or set(account) != {"customer_id", "campaigns"}:
            raise MetricsIncomplete("계정 자료 모양이 아닙니다")
        cid = account["customer_id"]
        if type(cid) is not int or cid not in expected or cid in seen:
            raise MetricsIncomplete("계정 자료가 겹치거나 빠졌습니다")
        seen.add(cid)
        campaigns = account["campaigns"]
        if not isinstance(campaigns, list) or not 0 < len(campaigns) <= MAX_CAMPAIGNS:
            raise MetricsIncomplete("캠페인 목록이 완결되지 않았습니다")
        for campaign in campaigns:
            if not isinstance(campaign, dict) or set(campaign) != {"campaign_id", "cycle_base_tm", "summary", "days"}:
                raise MetricsIncomplete("캠페인 자료 모양이 아닙니다")
            campaign_id = campaign["campaign_id"]
            if not isinstance(campaign_id, str) or not N._CAMPAIGN_ID.fullmatch(campaign_id) or campaign_id in campaigns_seen:
                raise MetricsIncomplete("캠페인 번호가 겹치거나 다릅니다")
            campaigns_seen.add(campaign_id)
            _cycle(campaign["cycle_base_tm"], today, now)
            # 보충한 0만 보관하지 않는다. 원래 일별 자료와 같은 기간 합계로 매번 다시 증명한다.
            rows = reconcile(campaign["days"], campaign["summary"], today)
            for row in rows.values():
                if not isinstance(row, dict) or set(row) != set(FIELDS):
                    raise MetricsIncomplete("하루 지표 모양이 아닙니다")
                for name in FIELDS:
                    totals[name] = number(totals[name] + number(row[name]))
    start, end, _ = window(today)
    return dict(possibility_id=possibility_id, period_start=start.isoformat(), period_end=end.isoformat(),
                **{out: totals[src] for src, out in zip(FIELDS, OUTPUT_FIELDS)})


def _read_account(reader, row, context, today, clock, guard):
    handle = H.issue_check_handle(customer_id=row["customer_id"], possibility_id=row["possibility_id"],
                                  link_state=row["state"], stage=row["stage_key"],
                                  stage_as_of=context["stage_as_of"], latest_end_date=row["latest_end_date"], now=clock())
    guard()
    raw = reader.get_campaigns(handle)
    guard()
    if not raw or len(raw) > MAX_CAMPAIGNS:
        raise MetricsIncomplete("캠페인 목록이 완결되지 않았습니다")
    ids = []
    for campaign in raw:
        cid = campaign.get("nccCampaignId") if isinstance(campaign, dict) else None
        if not isinstance(cid, str) or not N._CAMPAIGN_ID.fullmatch(cid) or cid in ids \
                or campaign.get("customerId") != row["customer_id"]:
            raise MetricsIncomplete("캠페인 목록이 겹치거나 다릅니다")
        ids.append(cid)
    start, end, _ = window(today)
    summary = reader.get_stats_summary(handle, ids, start, end, fields=FIELDS)
    guard()
    summary_cycle = _cycle(summary.cycle_base_tm, today, clock())
    if set(summary.rows) != set(ids):
        raise MetricsIncomplete("기간 합계가 완결되지 않았습니다")
    campaigns = []
    for campaign_id in ids:
        guard()
        daily = reader.get_stats_daily(handle, campaign_id, start, end, fields=FIELDS)
        guard()
        cycle = min(summary_cycle, _cycle(daily.cycle_base_tm, today, clock()))
        reconcile(daily.days, summary.rows[campaign_id], today)
        campaigns.append({"campaign_id": campaign_id, "cycle_base_tm": cycle.isoformat(),
                          "summary": summary.rows[campaign_id], "days": daily.days})
    # 목록을 읽는 사이 추가/삭제된 캠페인을 놓친 자료는 보내지 않는다.
    guard()
    after = reader.get_campaigns(handle)
    guard()
    after_ids = [c.get("nccCampaignId") for c in after if isinstance(c, dict) and c.get("customerId") == row["customer_id"]]
    if len(after_ids) != len(after) or len(after_ids) != len(ids) or set(after_ids) != set(ids):
        raise MetricsIncomplete("읽는 사이 캠페인 목록이 바뀌었습니다")
    return {"customer_id": row["customer_id"], "campaigns": campaigns}


def run_metrics(reader, store, clock, poster, *, limit=2, max_seconds=45):
    """08:10~18:00에 제한된 가망만. 지표 전송 실패는 아침 점검·심박 상태를 바꾸지 않는다."""
    if type(limit) is not int or not 1 <= limit <= 20 or type(max_seconds) not in (int, float) or not 0 < max_seconds <= 60:
        raise ValueError("성과 작업 한도가 올바르지 않습니다")
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("시각은 시간대가 있어야 합니다")
    local = now.astimezone(S.KST)
    if not START <= local.time().replace(tzinfo=None) < END:
        return MetricsOutcome("OUTSIDE_WINDOW")
    context = store.metrics_context(now)
    if context is None:
        return MetricsOutcome("NOT_READY")
    fingerprint, today = context["fingerprint"], local.date()
    until = min(now + timedelta(seconds=max_seconds), datetime.combine(today, END, tzinfo=S.KST))
    started = monotonic()
    initial_calls = reader.calls
    counts = Counter()

    def guard():
        at = clock()
        if at < now or at >= until or monotonic() - started >= max_seconds \
                or at.astimezone(S.KST).date() != today or reader.calls - initial_calls >= MAX_CALLS:
            raise _BudgetExpired()

    work = store.metrics_work(fingerprint, now, limit)
    if not work:
        return MetricsOutcome("RETRY_WAIT", context["delivery_counts"])
    for pid in work:
        try:
            guard()
        except _BudgetExpired:
            return MetricsOutcome("BUDGET", dict(counts))
        try:
            store.begin_metrics_attempt(pid, fingerprint, clock())
            payload = store.metrics_payload(pid, fingerprint, clock())
            if payload is None:
                accounts = [_read_account(reader, row, context, today, clock, guard) for row in context["pairs"][pid]]
                guard()
                store.record_metrics_snapshot(pid, fingerprint, accounts, clock())
            guard()
            # 재시도라도 현재 짝/계정/단계/판단과 완결 원천을 마지막으로 다시 검사한다.
            payload = store.metrics_payload(pid, fingerprint, clock())
            if payload is None:
                raise MetricsIncomplete("전송할 자료가 없습니다")
            body = dict(payload, period_start=date.fromisoformat(payload["period_start"]),
                        period_end=date.fromisoformat(payload["period_end"]))
            result = poster.send_metrics(EA.build_metrics_payload(**body))
            outcome = "stored" if result.recorded else "no_client"
            store.finish_metrics_attempt(pid, fingerprint, clock(), outcome)
            counts[outcome] += 1
        except S.StoreRefused:
            return MetricsOutcome("SOURCE_CHANGED", dict(counts))
        except S.StoreError:
            raise
        except _BudgetExpired:
            store.finish_metrics_attempt(pid, fingerprint, clock(), "retry", error_kind="budget")
            return MetricsOutcome("BUDGET", dict(counts))
        except (MetricsIncomplete, H.NotEligible, H.HandleInvalid, N.StatsShapeUnknown):
            store.finish_metrics_attempt(pid, fingerprint, clock(), "held", error_kind="incomplete")
            counts["held"] += 1
        except (N.NaverApiError, N.RunAbort, EA.AlertSendError):
            store.finish_metrics_attempt(pid, fingerprint, clock(), "retry", error_kind="transport")
            counts["retry"] += 1
        except Exception:
            # 외부 예외 본문을 저장하거나 로그에 노출하지 않는다.
            store.finish_metrics_attempt(pid, fingerprint, clock(), "retry", error_kind="unexpected")
            counts["retry"] += 1
    return MetricsOutcome("DONE", dict(counts))
