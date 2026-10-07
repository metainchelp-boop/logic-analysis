"""fd73e935의 계정별 조회 기준. 기간 묶음 수정과 독립된 결과 동등성 oracle."""
from datetime import date, datetime, timedelta
import math

from naver_engine.store import KST, P, _rows


def performance_checks(self, now):
    """시도 상태와 마지막 성공 자료를 분리한다. 과거 값은 실제 기간을 함께 반환한다."""
    from naver_engine import management_store as MS
    decisions = MS.snapshot(self, now)
    attribution_changes = self.attribution_changes()
    # 목록에는 이어읽기/캠페인 JSON이 필요 없다. 큰 본문을 SQL 정렬·Python 행에 싣지 않는다.
    jobs = _rows(self._conn.execute("""SELECT job_key,customer_id,kind,cycle_day,period_start,period_end,
        snapshot_at,catalog_at,stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,
        attempts,error_code,progress_hash,bizmoney,bizmoney_at,last_success_at,last_bizmoney,last_bizmoney_at,
        previous_bizmoney,previous_bizmoney_at,generation,source_wait_attempts
        FROM naver_auto_performance_job ORDER BY checked_at,job_key"""))
    latest, success, balances, revalidations = {}, {}, {}, {}
    for job in jobs:
        cid = job["customer_id"]
        current_pid = decisions.get(cid, {}).get("possibility_id")
        if current_pid is not None and job["possibility_id"] != current_pid:
            continue
        if job["kind"] not in ("daily", "weekly", "manual"):
            if job["status"] != "superseded" and job["stage_revision"] == decisions.get(cid, {}).get("stage_revision"):
                revalidations[cid] = {key: job.get(key) for key in
                    ("kind", "status", "period_start", "period_end", "checked_at", "error_code", "generation")}
                revalidations[cid]["last_success_at"] = job.get("last_success_at") or (
                    job["checked_at"] if job["status"] == "ok" else None)
            if job["kind"] != "reconcile" or getattr(decisions.get(cid, {}).get("decision"), "cadence", None) != "weekly":
                continue
            # 비관리의 31일 정정 대조가 포함한 기존 7일 점검은 따로 그 기간만 투영한다.
            weekly = P.period_for("weekly", date.fromisoformat(job["cycle_day"]))
            job = {**job, "kind": "weekly", "period_start": str(weekly.since), "period_end": str(weekly.until)}
        latest[cid] = job
        last_at = job.get("last_success_at") or (job["checked_at"] if job["status"] == "ok" else None)
        if last_at is not None:
            good = {**job, "checked_at": last_at,
                    "bizmoney": job["last_bizmoney"] if job.get("last_success_at") else job["bizmoney"],
                    "bizmoney_at": job["last_bizmoney_at"] if job.get("last_success_at") else job["bizmoney_at"]}
            if cid not in success or last_at >= success[cid]["checked_at"]:
                success[cid] = good
            if good["bizmoney"] is not None and good["bizmoney_at"] is not None:
                balances.setdefault(cid, {})[good["bizmoney_at"]] = good["bizmoney"]
            if job.get("previous_bizmoney") is not None and job.get("previous_bizmoney_at") is not None:
                balances.setdefault(cid, {})[job["previous_bizmoney_at"]] = job["previous_bizmoney"]
    for request in _rows(self._conn.execute("SELECT * FROM naver_auto_manual_read WHERE consumed_at IS NULL")):
        cid = request["customer_id"]
        owner = decisions.get(cid)
        if not owner or owner["decision"].cadence == "blocked" or request.get("possibility_id") != owner["possibility_id"]:
            continue
        previous = revalidations.get(cid)
        if previous is not None and (previous.get("checked_at") or "") > request["requested_at"]:
            continue
        end = request.get("period_end") or str(datetime.fromisoformat(request["requested_at"]).date()-timedelta(days=1))
        start = request.get("period_start") or str(date.fromisoformat(end)-timedelta(
            days=0 if owner["decision"].cadence == "daily" else 6))
        revalidations[cid] = {"kind": request.get("request_kind") or ("manual_period" if request.get("period_start") else "manual"),
            "status": "pending", "period_start": start, "period_end": end, "checked_at": None,
            "requested_at": request["requested_at"], "error_code": None, "generation": request["requested_at"], "last_success_at": None}
    result = {}
    for cid, row in decisions.items():
        decision, attempt, good = row["decision"], latest.get(cid), success.get(cid)
        period = P.period_for(decision.cadence, now) if decision.cadence != "blocked" else None
        current = attempt is not None and period is not None and attempt["stage_revision"] == row["stage_revision"] and (
            (attempt["cycle_day"] == str(period.cycle_day) and attempt["kind"] == decision.cadence)
            or (attempt["kind"] == "manual" and attempt["cycle_day"] == str(now.astimezone(KST).date())))
        item = {"cadence": decision.cadence, "policy_reason": decision.reason,
                "attribution_changed": attribution_changes.get(cid, False),
                "stage_revision": row["stage_revision"],
                "excluded": decision.reason == "MANUAL_EXCLUSION",
                "status": attempt["status"] if current else "pending",
                "checked_at": attempt["checked_at"] if attempt is not None else None,
                "error_code": attempt["error_code"] if current else None,
                "last_success_at": good["checked_at"] if good else None,
                "period_start": good["period_start"] if good else None,
                "period_end": good["period_end"] if good else None,
                "stale": not (current and attempt["status"] == "ok"),
                "bizmoney": good["bizmoney"] if good else None,
                "bizmoney_at": good["bizmoney_at"] if good else None,
                "previous_bizmoney": None, "previous_bizmoney_at": None, "bizmoney_change": None,
                "spend": None, "imp": None, "clk": None,
                "revalidation": revalidations.get(cid), "source_rechecked_at": None}
        if good:
            history = sorted((at, balance) for at, balance in balances.get(cid, {}).items()
                             if good["bizmoney_at"] is not None and at < good["bizmoney_at"])
            if history:
                old_at, old_balance = history[-1]
                item.update(previous_bizmoney=old_balance, previous_bizmoney_at=old_at)
                if good["bizmoney"] is not None:
                    change = good["bizmoney"]-old_balance
                    item["bizmoney_change"] = change if math.isfinite(change) else None
            rows = self.daily_performance([cid], date.fromisoformat(good["period_start"]),
                                           date.fromisoformat(good["period_end"]))
            if row["possibility_id"] is not None:
                rows = [r for r in rows if r["possibility_id"] == row["possibility_id"]]
            count = (date.fromisoformat(good["period_end"])-date.fromisoformat(good["period_start"])).days+1
            if len(rows) == count and all(r["basic_complete"] for r in rows):
                item.update({k: sum(r[k] for r in rows) for k in ("spend", "imp", "clk")})
                verified = [r.get("checked_at") for r in rows]
                if all(verified):
                    item["source_rechecked_at"] = min(verified)
            item["activity_observed"] = any(r.get("spend", 0) > 0 or r.get("imp", 0) > 0 or r.get("clk", 0) > 0 for r in rows)
        result[cid] = item
    return result
