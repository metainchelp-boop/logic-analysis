"""Invented in-memory source4d fixtures; never opens an operating database.

The caller must verify the exact canonical source4d before supplying modules.
No production test helper is imported. Report generation is real except for its
mandatory synchronize_management hook: fixture preparation substitutes the
real pure MS.snapshot projection and forbids the original writer body. This
substitution is removed before returning the Store to the readonly reader.
No collection selector, HTTP transport, provider, socket or external DB runs.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import socket
import sqlite3
from unittest.mock import patch


SOURCE = "4d5802360c1ba23aa801b1145ca8483db3edd35f"
KST = timezone(timedelta(hours=9))
EVENT = datetime(2026, 10, 13, 7, 10, 30, tzinfo=KST)
NOW = datetime(2026, 10, 13, 7, 45, tzinfo=KST)
EXPIRES = EVENT + timedelta(minutes=1)
CID = 90001030001
ADNO = 1030001
PID = 51952
ACTOR = 100  # Invented fixture owner, not an assertion about any real actor.
PERIOD_KEY = "weekly:2026-10-05:2026-10-11"
JOB_ID = "a" * 32
TRACE_ID = "b" * 32
SCENARIOS = frozenset({
    "nojob", "ok", "empty_ok", "missing_metrics", "reading", "partial",
    "retry", "manual_pending", "consumed", "manual_ok", "expired_manual",
    "stale", "stale_catalog", "stale_snapshot",
})


def _forbidden(*_args, **_kwargs):
    raise AssertionError("FIXTURE_EXTERNAL_OR_SELECTOR_FORBIDDEN")


def _organization(at):
    def team(idx, name, level=1, parent=0, system=False):
        return dict(idx=idx, name=name, level=level, parent_idx=parent, is_system=system)

    def employee(idx, name, team_idx, manager=False, top=False):
        return dict(idx=idx, name=name, team_idx=team_idx, is_manager=manager,
                    is_top_manager=top, status="ACTIVE", is_deleted=False, is_management=True)

    return dict(generated_at=at.isoformat(),
        teams=[team(0, "미분류", 0, 0, True), team(1, "퇴사자", 0, 0, True),
               team(10, "합성 관리 본부"), team(11, "합성 관리 팀", 2, 10)],
        employees=[employee(0, "합성 대표", 0, True, True),
                   employee(1, "합성 팀장", 11, True), employee(ACTOR, "합성 담당", 11)],
        owners=[dict(possibility_id=PID, manage_emp_idx=ACTOR, sub_manage_emp_idx=None,
                     prev_manage_owner_idx=None, sales_emp_idx=None, owner_source="manage")])


def _accounts(S):
    return S.N.ChildAccounts(
        {CID: dict(customerId=CID, adAccountNo=ADNO, adAccountName="합성 Foodin")},
        {1: 1}, ())


def _catalog(st, at):
    st.record_account_catalog(dict(generated_at=at.isoformat(), total=1, complete=True,
        items=[dict(possibility_id=PID, company_name="합성 Foodin", stage="진행중",
                    stage_hidden=False, stage_known=True)]),
        [st_module(st).E.NaverIdRow(PID, "NAVER_SEARCHAD", ad_account_no_raw=str(ADNO))], at)


def st_module(st):
    # The actual class comes from the caller's canonical-verified module.
    import sys
    return sys.modules[type(st).__module__]


def _management(st, modules, at):
    revision = hashlib.sha256(f"{CID}:{PID}:진행중:1".encode()).hexdigest()
    # Fixture-only initial rows use the actual migrated schema. No selector or
    # synchronize body is called to fabricate current management ownership.
    with st._tx() as c:
        c.execute("""INSERT INTO naver_auto_management_state
            (customer_id,possibility_id,stage_key,stage_revision,revision,changed_at)
            VALUES(?,?,?,?,?,?)""", (CID, PID, "진행중", revision, 1, at.isoformat()))
        c.execute("""INSERT INTO naver_auto_management_event
            (customer_id,stage_revision,possibility_id,stage_key,action,at)
            VALUES(?,?,?,?,?,?)""", (CID, revision, PID, "진행중", "stage_sync", at.isoformat()))
    policy = modules["MS"].snapshot(st, at)[CID]
    if (policy["possibility_id"] != PID or policy["stage_revision"] != revision or
            policy["decision"].cadence != "daily" or not policy["source_current"]):
        raise AssertionError("FIXTURE_MANAGEMENT_NOT_CURRENT")


def _daily(st, at, revision):
    # Actual report generation consumes these invented, closed daily records.
    start = date(2026, 9, 28)
    with st._tx() as c:
        for offset in range(14):
            day = start + timedelta(days=offset)
            spend = 1000 + (revision * 100 if day >= date(2026, 10, 5) else 0)
            c.execute("""INSERT INTO naver_auto_daily_performance
                (customer_id,day,possibility_id,matching_fingerprint,basic_complete,
                 conversion_complete,conversion_attempts,imp,clk,spend,conversions,
                 conversion_value,checked_at,campaign_fingerprint,source_at,source_generation)
                VALUES(?,?,?,?,1,1,0,100,10,?,1,2000,?,?,?,?)
                ON CONFLICT(customer_id,day) DO UPDATE SET spend=excluded.spend,
                 checked_at=excluded.checked_at,source_at=excluded.source_at,
                 source_generation=excluded.source_generation""",
                (CID, day.isoformat(), PID, st.decision_fingerprint(), spend,
                 at.isoformat(), "synthetic-campaign-fingerprint", at.isoformat(),
                 at.replace(hour=0, minute=1, second=0, microsecond=0).isoformat()))
        c.execute("""INSERT INTO naver_auto_report_dirty
            (possibility_id,period_key,updated_at,pending) VALUES(?,?,?,1)
            ON CONFLICT(possibility_id,period_key) DO UPDATE SET updated_at=excluded.updated_at,pending=1""",
            (PID, PERIOD_KEY, at.isoformat()))


def _reports_and_event(st, modules):
    reads = []

    def pure_policy(now):
        reads.append(now)
        return modules["MS"].snapshot(st, now)

    # The class-level deny fence remains under this instance-only substitution:
    # accidental fallback to the actual synchronize body is a fixture failure.
    with patch.object(st, "synchronize_management", side_effect=pure_policy):
        for revision in range(1, 5):
            at = EVENT - timedelta(seconds=6-revision)
            _daily(st, at, revision)
            st.generate_reports(at)
    if len(reads) != 4:
        raise AssertionError("FIXTURE_REPORT_GENERATOR_BOUNDARY")
    row = st._conn.execute("""SELECT report_id,revision_fingerprint,payload_json
        FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=?
        ORDER BY report_id DESC LIMIT 1""", (PID, PERIOD_KEY)).fetchone()
    if row is None:
        raise AssertionError("FIXTURE_WEEKLY_REPORT_ABSENT")
    payload = json.loads(row[2])
    if (payload.get("revision_no") != 4 or payload.get("period_key") != PERIOD_KEY or
            {name: payload.get("period", {}).get(name) for name in ("kind", "start", "end")} !=
            dict(kind="weekly", start="2026-10-05", end="2026-10-11") or
            payload.get("_account_reports", {}).get(str(CID), {}).get("revision_no") != 4):
        raise AssertionError("FIXTURE_REAL_REPORT_REVISION_INVALID")
    key = modules["RV"].account_key(CID)
    created = EVENT - timedelta(seconds=1)
    prepared = st.prepare_learning_strategy(row[0], key, row[1], ACTOR, created, 0)
    st.create_learning_strategy_job(prepared, ACTOR, EXPIRES, created, JOB_ID)
    ack = st.reserve_observed_learning_call(prepared, ACTOR, EVENT, JOB_ID, 106496,
        None, trace_id=TRACE_ID, origin="manual_async", unlimited=True)
    if ack.get("binding") != {"bound": True}:
        raise AssertionError("FIXTURE_REAL_BINDING_UNCONFIRMED")
    # No provider is invoked. Only the real terminal persistence boundary runs.
    st.finish_learning_strategy_job(JOB_ID, EVENT + timedelta(seconds=15),
        diagnostic=dict(code="document-invalid", http_status=None))
    job = st.learning_strategy_job(job_id=JOB_ID)
    if (job is None or job["state"] != "failed" or
            not datetime.fromisoformat(job["updated_at"]) < EXPIRES < NOW):
        raise AssertionError("FIXTURE_HISTORICAL_JOB_TIME_INVALID")
    reservation = json.loads(st._conn.execute("SELECT value FROM naver_auto_meta WHERE key=?",
        ("learning-call:"+JOB_ID,)).fetchone()[0])
    if (job["report_id"] == 4 or job["expected_version"] != 0 or
            reservation["at"] != EVENT.isoformat(timespec="microseconds") or
            reservation["actor"] != ACTOR or reservation["proof_hash"] != job["proof_hash"] or
            reservation["report_id"] != job["report_id"] or reservation["account_key"] != key or
            reservation["possibility_id"] != PID):
        raise AssertionError("FIXTURE_REAL_EVENT_IDENTITY_INVALID")


def _inspection_job(st, modules, at, *, manual=False):
    policy = modules["MS"].snapshot(st, at)[CID]
    catalog = st.account_catalog()
    snapshot = st.inventory_snapshot(at)
    if manual:
        row = st._conn.execute("SELECT * FROM naver_auto_manual_read WHERE customer_id=?", (CID,))
        request = st_module(st)._rows(row)[0]
        job = st._inspection_manual_job(request, policy, snapshot,
            catalog["generated_at"], st.decision_fingerprint(), at)
        if job is None:
            raise AssertionError("FIXTURE_CURRENT_MANUAL_INVALID")
        return job
    period = modules["P"].period_for(policy["decision"].cadence, at)
    job = st._performance_job(CID, policy["decision"].cadence, period.cycle_day,
        period.since, period.until, policy, snapshot, catalog["generated_at"],
        matching_fingerprint=st.decision_fingerprint())
    job["job_key"] = "inspection:" + job["job_key"]
    return job


def _progress(job, modules, at, *, complete=True, empty=False, missing=False):
    R = modules["IR"]
    campaign = dict(customerId=CID, nccCampaignId="cmp-synthetic", name="합성 캠페인",
        dailyBudget=10000, useDailyBudget=True, campaignTp="WEB_SITE", userLock=False,
        delFlag=False)
    initial = R._initial([] if empty else [campaign], job, at)
    if not complete:
        return initial
    if empty:
        initial["confirmed"] = True
        return initial
    group = dict(customerId=CID, nccAdgroupId="grp-synthetic", nccCampaignId="cmp-synthetic",
        name="합성 그룹", adgroupType="WEB_SITE", bidAmt=1000, userLock=False)
    keyword = dict(customerId=CID, nccKeywordId="kwd-synthetic", nccAdgroupId="grp-synthetic",
        keyword="합성 상품", bidAmt=1130, useGroupBidAmt=False, userLock=True)
    ad = dict(customerId=CID, nccAdId="nad-synthetic", nccAdgroupId="grp-synthetic",
        type="TEXT_45", ad={"headline": "합성 소재"}, userLock=False)
    for kind, raw, parent in (("adgroup", group, "cmp-synthetic"),
                              ("keyword", keyword, "grp-synthetic"), ("ad", ad, "grp-synthetic")):
        key, entity = R._entity(kind, raw, parent, "cmp-synthetic", at)
        initial["entities"][key] = entity
    ids = sorted(row["id"] for row in initial["entities"].values())
    initial["queue"] = [R._task("adgroup", "cmp-synthetic"), R._task("ad", "grp-synthetic"),
        R._task("keyword", "grp-synthetic"),
        *[R._task("criterion", "grp-synthetic", criterion_type=kind) for kind in ("SD", "RL", "AG")],
        R._task("negative", "grp-synthetic"), R._task("stats", entity_ids=ids),
        R._task("verify_adgroup", "cmp-synthetic", entity_ids=["grp-synthetic"])]
    initial["next_index"] = len(initial["queue"])
    initial["targets"] = {"grp-synthetic": {kind: dict(state="observed", checked_at=at.isoformat(), records=[])
                                           for kind in R.TARGETS}}
    initial["performance"] = {key: dict(period_start=job["period_start"], period_end=job["period_end"],
        checked_at=at.isoformat(), source_at=None if missing else at.isoformat(),
        fields={name: None if missing else 0 for name in R.FIELDS}, complete=not missing, missing=missing)
        for key in initial["entities"]}
    initial["confirmed"] = True
    return initial


def _observe(st, modules, at, *, state="ok", manual=False, empty=False, missing=False):
    job = _inspection_job(st, modules, at, manual=manual)
    st.begin_inspection_check(job, at)
    if state == "reading":
        return job
    progress = _progress(job, modules, at, complete=state == "ok", empty=empty, missing=missing)
    st.record_inspection_progress(job, at, progress)
    values = dict(status=state)
    if state == "retry":
        values["error_code"] = "NETWORK"
    actual = st.record_inspection_check(job, at, values)
    if actual != state:
        raise AssertionError("FIXTURE_INSPECTION_STATE_CHANGED")
    return job


def seed(modules, scenario="nojob"):
    """Return (real Store, verified modules, NOW); all records are synthetic.

    Modules are supplied by the reader's source4d verify_source/load_modules
    boundary. The returned Store has writer=False. The caller installs its own
    query_only/readonly authorizer and explicit read transaction afterwards.
    """
    if type(modules) is not dict or any(key not in modules for key in ("S", "MS", "IR", "P", "RV")):
        raise ValueError("FIXTURE_MODULES_INVALID")
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise ValueError("FIXTURE_SCENARIO_INVALID")
    S = modules["S"]
    st = S.Store(sqlite3.connect(":memory:", isolation_level=None), ":memory:", None, True, lambda: NOW)
    try:
        with patch.object(socket.socket, "connect", side_effect=_forbidden), \
                patch.object(socket.socket, "connect_ex", side_effect=_forbidden), \
                patch.object(socket, "create_connection", side_effect=_forbidden), \
                patch.object(type(st), "inspection_work", side_effect=_forbidden), \
                patch.object(type(st), "performance_work", side_effect=_forbidden), \
                patch.object(type(st), "synchronize_management", side_effect=_forbidden):
            st._migrate()
            source_at = EVENT - timedelta(minutes=10)
            st.record_org(_organization(source_at), source_at)
            st.record_accounts(_accounts(S), source_at)
            _catalog(st, source_at)
            _management(st, modules, source_at)
            _reports_and_event(st, modules)
            checked = NOW - timedelta(minutes=1)
            if scenario in ("ok", "empty_ok", "missing_metrics", "manual_pending", "consumed",
                            "manual_ok", "expired_manual", "stale", "stale_catalog", "stale_snapshot"):
                _observe(st, modules, checked, empty=scenario == "empty_ok", missing=scenario == "missing_metrics")
            elif scenario in ("reading", "partial", "retry"):
                _observe(st, modules, checked, state=scenario)
            if scenario in ("manual_pending", "consumed", "manual_ok"):
                requested = NOW - timedelta(seconds=20)
                st.performance_manual_request(CID, ACTOR, requested)
                if scenario == "consumed":
                    with st._tx() as c:
                        c.execute("UPDATE naver_auto_manual_read SET consumed_at=requested_at WHERE customer_id=?", (CID,))
                elif scenario == "manual_ok":
                    _observe(st, modules, NOW-timedelta(seconds=10), manual=True)
            elif scenario == "expired_manual":
                requested = EVENT - timedelta(days=1)
                with st._tx() as c:
                    c.execute("""INSERT INTO naver_auto_manual_read
                        (customer_id,requested_at,actor,period_start,period_end,possibility_id,request_kind,consumed_at)
                        VALUES(?,?,?,?,?,?,?,?)""", (CID, requested.isoformat(), ACTOR, "2026-10-11", "2026-10-11",
                            PID, "manual", requested.isoformat()))
            elif scenario in ("stale", "stale_catalog"):
                _catalog(st, NOW-timedelta(seconds=1))
            elif scenario == "stale_snapshot":
                st.record_accounts(_accounts(S), NOW-timedelta(seconds=1))
        if any(name in st.__dict__ for name in ("inspection_work", "performance_work", "synchronize_management")):
            raise AssertionError("FIXTURE_SELECTOR_PATCH_NOT_REMOVED")
        st.writer = False
        return st, modules, NOW
    except BaseException:
        st.close()
        raise
