"""시험 전용 대조 사본 — 배포되지 않는다(봉인은 tests 폴더를 싣지 않는다 · discover 의 test*.py 에도 안 잡힌다).

NV-S00 2차(쓰기 줄 항목 CPU — 짝 맞추기 기억 · 지난 작업 계정별 묶음) 수정 전 판(a981b35)의 관리 판정(``snapshot``)과
수집 후보(``performance_work``)를 **글자 그대로** 옮겨 둔다. 바꾼 곳은 패키지 상대 가져오기 두 줄뿐이다
(원문은 ``from . import inventory as I`` · ``from . import store as S``). 들여쓰기는 메서드에서 함수로 한 단만 뺐다.
새 판(같은 입력이면 지난 짝 맞추기를 다시 씀 · 계정별 묶음)이 같은 입력에서 같은 판정 · 같은 후보 · 같은 표를 내는지
대조할 때 이 사본이 「정답」이다. ``performance_work`` 는 저장소의 ``synchronize_management`` 를 부르므로 시험은
``management_store.snapshot`` 을 이 사본의 ``snapshot`` 으로 바꿔 끼운 채 부른다(그러면 옛 판 전체 경로다).
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.naver_auto import org_snapshot as O

from naver_engine import management as P
from naver_engine.management_store import _organization
from naver_engine.store import _rows


def snapshot(store, now, *, stage_states=None) -> dict:
    """계정별 현재 판정. 네이버 호출·상태 갱신 없이 저장소의 공개 조회만 쓴다."""
    # inventory는 store를 참조하므로 저장소가 이 어댑터를 부른 뒤에 불러온다.
    from naver_engine import inventory as I

    accounts = {row["customer_id"]: row for row in store.accounts()}
    catalog, catalog_state = I.catalog_status(store, now)
    snapshot_at = store.inventory_snapshot(now)
    org = _organization(store)
    org_current = org is not None and O.allows_raising(O.org_freshness(org.generated_dt, now))
    current = catalog_state == "accepted" and snapshot_at is not None and org_current
    states = store.management_states() if stage_states is None else stage_states
    pairs, companies = {}, {}
    if current:
        companies = {row["possibility_id"]: row for row in catalog["items"]}
        result, _ = I._matching(SimpleNamespace(accounts=accounts, live_decisions=store.current_decisions()), catalog,
                               auto_evidence=I.automatic_evidence(store))
        pairs = {pair.customer_id: pair for pair in result.pairs}
    rows = {}
    for cid, account in accounts.items():
        pair = pairs.get(cid)
        company = companies.get(pair.possibility_id) if pair else None
        stage = company["stage"] if company and company["stage_known"] and not company["stage_hidden"] else None
        stage_key = "".join(stage.split()) if stage else None
        # 현재 이관 계정은 회사 귀속이 보류되어도 주간 원천 수집을 한다.
        # 숨김/미확인 업체의 번호 매칭을 직원 접근이나 ERP 귀속으로 승격하지 않는다.
        # 기존 연결 결정은 조회만 하며 이 분류 전환으로 지우지 않는다.
        pid = company["possibility_id"] if company and stage_key else None
        previous = states.get(cid, {})
        same_stage = previous.get("possibility_id") == pid and previous.get("stage_key") == stage_key
        revision = previous.get("stage_revision") if same_stage else None
        revision = revision or (f"pending:{pid}:{stage_key}" if pid is not None else None)
        excluded = previous.get("excluded_revision") if same_stage else None
        included = previous.get("included_revision") if same_stage else None
        decision = P.classify(stage=stage, stage_revision=revision, matched=pid is not None,
                              authority_valid=account["present"] == 1, source_current=current,
                              excluded_revision=excluded, included_revision=included)
        rows[cid] = {"decision": decision, "possibility_id": pid, "stage": stage, "stage_key": stage_key,
                     "stage_revision": revision, "excluded_revision": excluded, "matched": pid is not None,
                     "included_revision": included,
                     "_auto_identity": ((pair.possibility_id, pair.auto_identity_fingerprint)
                                        if pair and pair.auto_identity_fingerprint else None),
                     "snapshot_at": snapshot_at, "source_current": current, "catalog_status": catalog_state}
    return rows


def performance_work(self, now, limit=24):
    from naver_engine import store as S
    if type(limit) is not int or not 1 <= limit <= 24:
        raise S.StoreRefused("원천 후보는 1~24개입니다")
    if now.astimezone(S.KST).time().replace(tzinfo=None) < P.COLLECTION_START:
        return []
    decisions = self.synchronize_management(now)
    snapshot = self.inventory_snapshot(now)
    if snapshot is None:
        return []
    catalog = self.account_catalog()
    if catalog is None:
        return []
    # 단일 writer의 후보 생성 안에서는 연결 판단을 바꾸거나 외부 요청을 하지 않는다.
    # 이 묶음에서만 재사용하고 매 요청 직전 performance_account_valid는 새로 검증한다.
    matching_fingerprint = self.decision_fingerprint()
    day, at = now.astimezone(S.KST).date(), S._kst_text(now, "현재")
    prior = {r["job_key"]: r for r in _rows(self._conn.execute(
        """SELECT * FROM naver_auto_performance_job WHERE cycle_day>=?
           OR status IN ('reading','partial','retry','source_wait')""",
        ((day-timedelta(days=40)).isoformat(),)))}
    candidates = []
    backfill = []

    def available(job):
        saved = prior.get(job["job_key"])
        if saved and saved["stage_revision"] != job["stage_revision"]:
            return None, True
        if saved and not self._collection_retry_ready(saved, at):
            return saved, False
        return saved, True

    def covered(job):
        # 당일/동일 이후 세대의 전체 성공 또는 진행 회차가 포함하면 목적만 재사용한다.
        return any(saved["customer_id"] == job["customer_id"]
                   and saved["stage_revision"] == job["stage_revision"]
                   and saved.get("possibility_id") == decisions[job["customer_id"]]["possibility_id"]
                   and saved.get("generation", "") >= job["generation"]
                   and saved["period_start"] <= job["period_start"] <= job["period_end"] <= saved["period_end"]
                   and saved["status"] not in ("limited", "reauth_required")
                   and saved["job_key"] != job["job_key"] for saved in prior.values())

    for cid, row in decisions.items():
        decision = row["decision"]
        if decision.cadence == "blocked":
            continue
        period = P.period_for(decision.cadence, day)
        job = self._performance_job(cid, decision.cadence, period.cycle_day, period.since,
                                    period.until, row, snapshot, catalog["generated_at"],
                                    matching_fingerprint=matching_fingerprint)
        old = prior.get(job["job_key"])
        if old and old["stage_revision"] != job["stage_revision"]:
            old = None
        recheck = old is not None and old["status"] == "ok" and decision.cadence == "daily" \
            and self._performance_conversion_due(job, row["possibility_id"], now)
        # 저장된 고정 기간은 자정/10시 뒤에도 이어 읽되 현재 권한·귀속을 재검증한다.
        for saved in prior.values():
            if saved["customer_id"] != cid or saved["stage_revision"] != row["stage_revision"] \
                    or saved["kind"] in ("manual", "manual_period") or saved["job_key"] == job["job_key"]:
                continue
            carry = self._performance_job(cid, saved["kind"], date.fromisoformat(saved["cycle_day"]),
                date.fromisoformat(saved["period_start"]), date.fromisoformat(saved["period_end"]),
                row, snapshot, catalog["generated_at"], matching_fingerprint=matching_fingerprint)
            carry["generation"] = saved.get("generation") or carry["generation"]
            _, due = available(carry)
            if due and not covered(carry) and self.performance_account_valid(carry, now):
                backfill.append((2, saved["checked_at"], cid, carry))
        prior_managed = False
        if decision.cadence != "daily" and day.weekday() == 6 and row["possibility_id"] is not None:
            prior_managed = self._performance_has_managed_history(cid, row["possibility_id"])
        fills = []
        planned = P.revalidation_periods(day, managed=decision.cadence == "daily", prior_managed=prior_managed)
        if decision.cadence == "daily" and not (old and old["status"] == "ok"):
            planned = []
        elif decision.cadence == "daily":
            month_start, month_end = day.replace(day=1), day-timedelta(days=1)
            complete = {r["day"] for r in self.daily_performance([cid], month_start, month_end)
                        if r["basic_complete"] and r["possibility_id"] == row["possibility_id"]}
            missing = [month_start+timedelta(days=n) for n in range(max(0,(month_end-month_start).days+1))
                       if str(month_start+timedelta(days=n)) not in complete]
            if missing:
                planned.append(("backfill", day, min(missing), month_end))
        for kind, cycle, since, until in planned:
            fill = self._performance_job(cid, kind, cycle, since, until, row, snapshot, catalog["generated_at"],
                                        matching_fingerprint=matching_fingerprint)
            saved, due = available(fill)
            if due and not covered(fill) and not any(f["period_start"] <= fill["period_start"]
                    and fill["period_end"] <= f["period_end"] and f["generation"] >= fill["generation"] for f in fills):
                fills.append(fill)
                # 최초 수집을 우선하되 별도 예산 예약이 보충의 진행 기회를 보장한다.
                backfill.append((2, fill["generation"] if saved is None else saved["checked_at"], cid, fill))
        if fills:
            # 과거 미완료 단일일을 새 보충 범위에 합친다. 원래 작업의 기간/체크포인트는
            # 보존하고 포함 범위 성공 후에만 superseded로 종료한다.
            backfill = [item for item in backfill if item[2] != cid or item[3] in fills or not any(
                fill["period_start"] <= item[3]["period_start"] <= item[3]["period_end"] <= fill["period_end"]
                and fill["generation"] >= item[3]["generation"] for fill in fills)]
        complete = period.cycle_day if old and old["status"] == "ok" and not recheck else None
        started = period.cycle_day if old else None
        if not P.is_due(decision, day, completed_cycle=complete, started_cycle=started):
            continue
        if covered(job) or (decision.cadence == "weekly" and any(f["kind"] == "reconcile" for f in fills)):
            continue
        if old and not recheck and not self._collection_retry_ready(old, at):
            continue
        candidates.append((0 if decision.cadence == "daily" else 1,
                           "" if old is None else old["checked_at"], cid, job))
    for request in _rows(self._conn.execute("SELECT * FROM naver_auto_manual_read")):
        cid = request["customer_id"]
        row = decisions.get(cid)
        if row is None or row["decision"].cadence == "blocked":
            continue
        request_day = datetime.fromisoformat(request["requested_at"]).astimezone(S.KST).date()
        if (day-request_day).days > 7 and request.get("consumed_at") is None:
            continue
        end = date.fromisoformat(request["period_end"]) if request.get("period_end") else request_day-timedelta(days=1)
        start = date.fromisoformat(request["period_start"]) if request.get("period_start") else (
            end if row["decision"].cadence == "daily" else end-timedelta(days=6))
        kind = request.get("request_kind") or ("manual_period" if request.get("period_start") else "manual")
        manual = self._performance_job(cid,kind,request_day,start,end,row,snapshot,catalog["generated_at"],
                                       matching_fingerprint=matching_fingerprint)
        manual["job_key"] += ":"+request["requested_at"]
        manual.update(requested_at=request["requested_at"],actor=request["actor"],generation=request["requested_at"])
        if not self.performance_account_valid(manual, now):
            continue
        saved = prior.get(manual["job_key"])
        if saved and saved["stage_revision"] != manual["stage_revision"]:
            saved = None
        if saved and not self._collection_retry_ready(saved, at):
            continue
        candidates.append((-1, "" if saved is None else saved["checked_at"], cid, manual))
    selected, used, manual_count = [], set(), 0
    lane_counts, account_ready = [0, 0], {}
    daily_waiting = any(item[3]["kind"] == "daily" for item in candidates)
    for _, _, cid, job in sorted(candidates+backfill, key=lambda item: (*item[:3], item[3]["job_key"])):
        if job["kind"] in ("manual", "manual_period") and daily_waiting and manual_count >= 1:
            continue
        # 최초/보충을 각각 후보로 두되 실제 reader가 계정 중복 호출을 막는다.
        supplemental = job["kind"] not in ("daily", "weekly", "manual") \
            or (job["kind"] == "daily" and job["cycle_day"] < str(day))
        if lane_counts[supplemental] >= limit:
            continue
        if cid not in account_ready:
            account_ready[cid] = self._collection_account_ready(cid, at)
        if not account_ready[cid]:
            continue
        lane = (cid, supplemental)
        if lane not in used:
            selected.append(job)
            used.add(lane)
            lane_counts[supplemental] += 1
            manual_count += job["kind"] in ("manual", "manual_period")
    primary = [j for j in selected if j["kind"] in ("daily", "weekly", "manual")
               and not (j["kind"] == "daily" and j["cycle_day"] < str(day))]
    supplement = [j for j in selected if j not in primary]
    reserve = min(6, len(supplement), limit//3) if primary else limit
    return primary[:limit-reserve]+supplement[:max(reserve, limit-len(primary))]

