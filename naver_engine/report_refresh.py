"""저장판 수치와 분리한 조회 전용 갱신 상태. 수집/생성/저장은 하지 않는다."""
from datetime import datetime, timedelta

from . import reporting as R


def _time(raw):
    try:
        at = datetime.fromisoformat(raw or "")
        return at.astimezone(R.KST) if at.tzinfo is not None and at.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def source_collected_at(rows, now):
    times = []
    for row in rows:
        checked, source, generation = (_time(row.get(key)) for key in ("checked_at", "source_at", "source_generation"))
        if (checked and source and generation and source <= checked <= now and generation <= checked
                and source.date() >= generation.date() and R._collected(row, row.get("day"), now)):
            times.append(checked)
    return max(times).isoformat() if times else None


def scope_state(period, expected, rows, jobs, queued, prior, required_after, dirty, now):
    """이미 저장된 원천·작업 증거만 사용한다. 전환 미확인을 0/성공으로 바꾸지 않는다."""
    by_day = {(row["customer_id"], row["day"]): row for row in rows}
    pending, failed, attempts, proven = 0, False, [], []
    for cid in expected:
        for offset in range((period.end-period.start).days+1):
            day = str(period.start+timedelta(days=offset))
            row = by_day.get((cid, day))
            base = _time((required_after or {}).get(str(cid))) or period.due_at.replace(hour=0, minute=1)
            checked, source, generation = (_time((row or {}).get(key))
                for key in ("checked_at", "source_at", "source_generation"))
            proof = bool(row and row["basic_complete"] and row["conversion_complete"]
                and checked and source and generation and base <= generation <= checked <= now
                and source <= checked and source.date() >= generation.date() and R._collected(row, day, now))
            if proof:
                proven.append(checked)
            relevant = [job for job in jobs if job["customer_id"] == cid and job["period_start"] <= day <= job["period_end"]]
            newest = relevant[-1] if relevant else None
            good = proof
            if newest:
                attempted = _time(newest.get("checked_at"))
                if attempted is None or attempted > now:
                    good = False
                else:
                    attempts.append(attempted)
                required = _time(newest.get("generation"))
                if required and (generation is None or generation < required):
                    good = False
                if newest["status"] != "ok" and attempted is not None and attempted <= now and (checked is None or attempted >= checked):
                    good = False
                    failed = failed or newest["status"] in ("retry", "limited", "reauth_required")
            if any(request["customer_id"] == cid and request["period_start"] <= day <= request["period_end"] for request in queued):
                good = False
            if not good:
                pending += 1
    status = "complete" if expected and not pending else "failed" if failed else "pending"
    if dirty and status == "complete":
        status = "updating"
    successes = [_time(prior.get("last_checked_at"))]
    if expected and len(proven) == len(expected)*((period.end-period.start).days+1):
        successes.append(min(proven))
    successful = [at for at in successes if at is not None and at <= now]
    source_attempts = [_time(row.get("checked_at")) for row in rows]
    source_attempts = [at for at in source_attempts if at is not None and at <= now]
    attempted = max(attempts) if len(attempts) > 0 else max(source_attempts, default=None)
    validation = {"status": status, "pending_account_days": pending,
        "last_checked_at": max(successful).isoformat() if successful else None,
        "last_attempt_at": attempted.isoformat() if attempted is not None else None}
    return {"validation": validation, "source_collected_at": source_collected_at(rows, now)}
