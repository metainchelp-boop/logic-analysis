"""일별 정정 큐를 같은 읽기 거래에서 계산하고 업체 단위로 원자 게시한다."""
from datetime import date, datetime, timedelta
from contextlib import contextmanager
import hashlib
import json

from . import reporting as R


@contextmanager
def _read_snapshot(store):
    """조회 도중 writer가 게시해도 옛 숫자와 새 대조 상태가 섞이지 않는다."""
    own = not store._conn.in_transaction
    if own:
        store._conn.execute("BEGIN")
    try:
        yield
        if own:
            store._conn.execute("COMMIT")
    except Exception:
        if own and store._conn.in_transaction:
            store._conn.execute("ROLLBACK")
        raise


def _period(key):
    from .store import StoreRefused
    try:
        kind, start, end = key.split(":")
        value = R.period(kind, date.fromisoformat(start))
        if value.key != key:
            raise ValueError()
        return value
    except (AttributeError, TypeError, ValueError):
        raise StoreRefused("보고 기간이 올바르지 않습니다") from None


def _source_fingerprint(rows):
    values = [[row["customer_id"], row["day"], row.get("source_revision", 0),
               row["basic_complete"], row["conversion_complete"],
               *[row.get(key) for key in R.OUTPUT_FIELDS]] for row in rows]
    values.sort(key=lambda item: (item[0], item[1]))
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _validation(store, pid, period, expected, rows, now, *, source_fingerprint=None, required_after=None):
    from .store import _rows
    # 숫자 완결과 보고기간의 요구된 재대조 완료는 별개다.
    required = period.due_at.replace(hour=0, minute=1)
    jobs = _rows(store._conn.execute("""SELECT * FROM naver_auto_performance_job
        WHERE possibility_id=? AND period_start<=? AND period_end>=? ORDER BY checked_at""",
        (pid, period.end.isoformat(), period.start.isoformat())))
    by_day = {(row["customer_id"], row["day"]): row for row in rows}
    pending, failed, attempts, successes = 0, False, [], []
    for cid in expected:
        for offset in range((period.end-period.start).days+1):
            day = (period.start+timedelta(days=offset)).isoformat()
            row = by_day.get((cid, day))
            relevant = [job for job in jobs if job["customer_id"] == cid and
                        job["period_start"] <= day <= job["period_end"]]
            checked = datetime.fromisoformat(row["checked_at"]) if row else None
            day_required = datetime.fromisoformat(required_after[str(cid)]) if required_after and str(cid) in required_after else required
            newest = relevant[-1] if relevant else None
            if newest:
                attempts.append(newest["checked_at"])
                generation = newest.get("generation")
                if generation:
                    day_required = max(day_required, datetime.fromisoformat(generation))
            good = bool(row and row["basic_complete"] and row["conversion_complete"] and checked >= day_required)
            if newest and newest["status"] != "ok" and (checked is None or newest["checked_at"] >= row["checked_at"]):
                good = False
                failed = failed or newest["status"] in ("retry", "limited", "reauth_required")
            if good:
                successes.append(row["checked_at"])
            else:
                pending += 1
    return {"status": "complete" if expected and not pending else "failed" if failed else "pending",
            "last_attempt_at": max(attempts) if attempts else max((r["checked_at"] for r in rows), default=None),
            "last_checked_at": min(successes) if expected and not pending else None,
            "pending_account_days": pending,
            "source_snapshot_fingerprint": source_fingerprint or _source_fingerprint(rows)}


def _public_validation(value):
    return {key: item for key, item in value.items() if not key.startswith("_")}


def generate(store, now):
    from . import store as S
    store._need_writer()
    at = S._kst_text(now, "생성 시각")
    store._not_future(now, "생성 시각")
    decisions = store.synchronize_management(now)
    confirmed = {d.customer_id: d.possibility_id for d in store.current_decisions() if d.decision == "confirmed"}
    historical = set(store._conn.execute("""SELECT DISTINCT customer_id,possibility_id
        FROM naver_auto_performance_job WHERE kind='daily' AND status='ok'"""))
    groups = {}
    for cid, value in decisions.items():
        pid, cadence = value["possibility_id"], value["decision"].cadence
        if pid is not None and confirmed.get(cid) == pid and cadence != "blocked" and (
                cadence == "daily" or (cid, pid) in historical):
            groups.setdefault(pid, []).append(cid)
    today = now.astimezone(S.KST).date()
    periods = R.due_periods(now, (today.replace(day=1)-timedelta(days=1)).replace(day=1))
    issues = {row["possibility_id"] for row in store.issues(open_only=True)}
    # 초판만 등록한다. 기존 판의 재계산은 수집의 같은 거래에서 쌓은 dirty가 담당한다.
    with store._tx() as connection:
        for pid in groups:
            for period in periods:
                connection.execute("""INSERT INTO naver_auto_report_dirty
                    (possibility_id,period_key,updated_at,pending) VALUES(?,?,?,1)
                    ON CONFLICT(possibility_id,period_key) DO NOTHING""", (pid, period.key, at))
    # 한 업체의 주간·월간을 절단하지 않는다. 대기 업체는 오래된 순서로 계속 배출한다.
    dirty = S._rows(store._conn.execute("""SELECT possibility_id,period_key,updated_at
        FROM naver_auto_report_dirty WHERE pending=1 ORDER BY updated_at,possibility_id,period_key"""))
    batches = {}
    for item in dirty:
        period = _period(item["period_key"])
        if period.due_at > now:
            continue
        pid = item["possibility_id"]
        if pid not in batches and len(batches) >= 20:
            continue
        batches.setdefault(pid, []).append(period)
    made = 0
    for pid, targets in batches.items():
        with store._tx() as connection:
            prepared, batch_rows = [], {}
            for period in targets:
                state = connection.execute("""SELECT expected_customers_json,payload_json
                    FROM naver_auto_report_validation WHERE possibility_id=? AND period_key=?""",
                    (pid, period.key)).fetchone()
                historical_ids = [row[0] for row in connection.execute("""SELECT DISTINCT customer_id
                    FROM naver_auto_daily_performance WHERE possibility_id=? AND day BETWEEN ? AND ?""",
                    (pid, period.start.isoformat(), period.end.isoformat()))]
                expected = sorted(set(json.loads(state[0]) if state else groups.get(pid, [])) | set(historical_ids))
                rows = store.daily_performance(expected, period.start, period.end, possibility_id=pid)
                batch_rows.update({(row["customer_id"], row["day"]): row for row in rows})
                previous = S._rows(connection.execute("""SELECT * FROM naver_auto_report_snapshot
                    WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""", (pid, period.key)))
                report = R.aggregate(period, expected, rows, now, has_open_issues=pid in issues)
                prepared.append((period, expected, rows, previous[0] if previous else None, report, state))
            source = _source_fingerprint(list(batch_rows.values()))
            for period, expected, rows, previous, report, state in prepared:
                required_after = {}
                for cid in expected:
                    required = period.due_at.replace(hour=0, minute=1)
                    decision = decisions.get(cid, {}).get("decision")
                    if decision is not None and decision.cadence == "weekly":
                        # 비관리 보고서는 직전 일요일 대조를 재사용한다. 평일 회차를 요구하지 않는다.
                        required -= timedelta(days=(required.weekday()+1) % 7)
                    required_after[str(cid)] = required.isoformat()
                validation = _validation(store, pid, period, expected, rows, now,
                                         source_fingerprint=source, required_after=required_after)
                prior_validation = json.loads(state[1]) if state else {}
                if validation["last_checked_at"] is None:
                    validation["last_checked_at"] = prior_validation.get("last_checked_at")
                if not previous or previous["revision_fingerprint"] != report["revision_fingerprint"]:
                    old_payload = json.loads(previous["payload_json"]) if previous else None
                    # 기존 판은 수정하지 않는다. 되돌아온 값도 새 판으로 보존한다.
                    revision = connection.execute("""SELECT COUNT(*) FROM naver_auto_report_snapshot
                        WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()[0]+1
                    report.update(revision_no=revision,
                                  change_summary=R.revision_metadata(old_payload, report, previous["report_id"] if previous else None),
                                  validation=_public_validation(validation))
                    connection.execute("""INSERT INTO naver_auto_report_snapshot
                        (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                        VALUES(?,?,?,?,?,?,?)""", (pid, period.key, report["revision_fingerprint"], at,
                                                  report["status"], report["review_status"], S._json(report)))
                    made += 1
                validation["_required_after"] = required_after
                connection.execute("""INSERT INTO naver_auto_report_validation
                    (possibility_id,period_key,expected_customers_json,payload_json) VALUES(?,?,?,?)
                    ON CONFLICT(possibility_id,period_key) DO UPDATE SET
                    expected_customers_json=excluded.expected_customers_json,payload_json=excluded.payload_json""",
                    (pid, period.key, S._json(expected), S._json(validation)))
                connection.execute("""UPDATE naver_auto_report_dirty SET pending=0
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key))
    return {"generated": made, "accounts_confirmed": len(confirmed), "advertisers": len(batches)}


def require_scope(store, pid, actor, now, action):
    from . import inventory as I, views as W, store as S
    from app.naver_auto import scope as SC
    org = W.load_org(store)
    catalog, state = I.catalog_status(store, now)
    if state != "accepted":
        raise S.StoreRefused("최신 전산 업체를 확인한 뒤 다시 조회해 주세요")
    company = next((row for row in catalog["items"] if row["possibility_id"] == pid), None)
    visible = company is not None and company["stage_known"] and not company["stage_hidden"]
    own = SC.ownership_for_client(org, pid, pid, SC.MATCH_PID if visible else SC.MATCH_UNKNOWN)
    SC.require_client(org, SC.scope_of(org, actor), {pid: own} if visible else {}, pid, action)


def present(store, rows, *, current=False):
    from . import store as S
    output = []
    for row in rows:
        payload = json.loads(row.pop("payload_json"))
        row["payload"] = {key: value for key, value in payload.items() if not key.startswith("_")}
        row["revision_no"] = payload.get("revision_no") or store._conn.execute("""SELECT COUNT(*)
            FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? AND report_id<=?""",
            (row["possibility_id"], row["period_key"], row["report_id"])).fetchone()[0]
        row["change_summary"] = payload.get("change_summary")
        row["validation"] = payload.get("validation", {"status": "pending", "last_checked_at": None})
        if current:
            saved = store._conn.execute("""SELECT expected_customers_json,payload_json FROM naver_auto_report_validation
                WHERE possibility_id=? AND period_key=?""", (row["possibility_id"], row["period_key"])).fetchone()
            dirty = store._conn.execute("""SELECT pending FROM naver_auto_report_dirty
                WHERE possibility_id=? AND period_key=?""", (row["possibility_id"], row["period_key"])).fetchone()
            if saved:
                row["validation"] = json.loads(saved[1])
                if dirty and dirty[0]:
                    period = _period(row["period_key"])
                    expected = json.loads(saved[0])
                    sources = store.daily_performance(expected, period.start, period.end, possibility_id=row["possibility_id"])
                    latest = _validation(store, row["possibility_id"], period, expected, sources, store._now(),
                                         required_after=row["validation"].get("_required_after"))
                    latest["last_checked_at"] = row["validation"].get("last_checked_at")
                    if latest["status"] == "complete":
                        latest["status"] = "updating"
                    row["validation"] = latest
        reviews = S._rows(store._conn.execute("""SELECT * FROM naver_auto_report_review
            WHERE report_id=? ORDER BY review_id DESC LIMIT 1""", (row["report_id"],)))
        row["review"] = reviews[0] if reviews else None
        if row["review"]:
            row["review_status"] = row["review"]["decision"]
        row["validation"] = _public_validation(row["validation"])
        row["payload"]["validation"] = row["validation"]
        output.append(row)
    return output


def snapshots(store):
    from .store import _rows
    with _read_snapshot(store):
        rows = _rows(store._conn.execute("""SELECT r.* FROM naver_auto_report_snapshot r
            WHERE r.report_id=(SELECT MAX(n.report_id) FROM naver_auto_report_snapshot n
                WHERE n.possibility_id=r.possibility_id AND n.period_key=r.period_key)
            ORDER BY generated_at DESC,report_id DESC"""))
        return present(store, rows, current=True)


def history(store, possibility_id, actor, now, *, period_key=None, before_report_id=None, limit=20):
    from . import store as S
    from app.naver_auto import scope as SC
    S._pos_int(possibility_id, "업체")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise S.StoreRefused("보고서 이력은 1~50개씩 조회합니다")
    if period_key is not None:
        _period(period_key)
    if before_report_id is not None:
        S._pos_int(before_report_id, "이전 보고서")
    clauses, values = ["possibility_id=?"], [possibility_id]
    if period_key is not None:
        clauses.append("period_key=?")
        values.append(period_key)
    if before_report_id is not None:
        clauses.append("report_id<?")
        values.append(before_report_id)
    with _read_snapshot(store):
        require_scope(store, possibility_id, actor, now, SC.ACT_VIEW)
        rows = S._rows(store._conn.execute("SELECT * FROM naver_auto_report_snapshot WHERE "+
                       " AND ".join(clauses)+" ORDER BY report_id DESC LIMIT ?", (*values, limit+1)))
        return {"items": present(store, rows[:limit]),
                "next_before_report_id": rows[limit-1]["report_id"] if len(rows) > limit else None}
