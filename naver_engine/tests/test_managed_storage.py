"""실제 Store/Writer·합성 GET 통합. 운영 호출·단일 writer 잠금 우회 없음.

Mac의 Store 연결 환경 오류는 기능 실패와 별도다. Linux CI에서는 실제 잠금으로
실행하며, 저장 이력 확인만 별도 읽기 전용 SQLite 연결로 한다.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import socket
import sqlite3
import unittest
from unittest.mock import patch

from naver_engine import erp_read as E, performance_reads as P, store as S
from naver_engine.tests import test_account_catalog as TC, test_alerts as TA, test_morning as TM
from naver_engine.tests.fake_naver import FakeNaver, cycle_str
from app.naver_auto import matching as M, scope as SC


class _Rows:
    def __init__(self, rows):
        self.names = tuple(rows[0]) if rows else ()
        self.description = [(name,) for name in self.names]
        self.rows = [tuple(row[name] for name in self.names) for row in rows]

    def __iter__(self):
        return iter(self.rows)

    def fetchone(self):
        return next(iter(self.rows), None)


class _ManagedBoundary(S.ManagedStorage):
    """SQL/원천 경계의 fixture. 실제 SQLite 연결이나 writer 잠금을 대체하지 않는다."""
    def __init__(self, now):
        self.now = now
        self._conn = self
        self.jobs, self.requests, self.events, self.daily_rows = [], [], [], []
        self.structure_jobs = []
        self.progress = None
        self.catalog_state = "accepted"
        self.catalog = {"generated_at": now.isoformat(), "total": 1, "complete": True,
                        "items": [{"possibility_id": 11, "company_name": "가상 상점", "stage": "진행중",
                                   "stage_known": True, "stage_hidden": False}],
                        "ids": [{"possibility_id": 11, "vendor": M.VENDOR_NAVER,
                                 "customer_id_raw": str(TM.A), "ad_account_no_raw": None}]}
        self.states = {TM.A: {"stage_revision": "revision-1", "excluded_revision": None,
                             "included_revision": None, "possibility_id": 11, "stage_key": "진행중"}}

    def execute(self, sql, args=()):
        # 공유 계정 대기 조회는 전체 작업 행이 아니라 정해진 5열의 최신 한 행이다.
        if " ".join(sql.split()).startswith("SELECT status,error_code,checked_at,next_try_at,attempts FROM "):
            source = self.structure_jobs if "naver_auto_structure_job" in sql else self.jobs
            eligible = [(index,row) for index,row in enumerate(source)
                        if row["customer_id"] == args[0] and (row["status"] == "ok"
                        or row.get("error_code") in ("KEY_REJECTED","RATE","SERVER","NETWORK"))]
            if not eligible:
                return _Rows([])
            _, row = max(eligible,key=lambda entry:(entry[1]["checked_at"],entry[0]))
            return _Rows([{"status":row["status"],"error_code":row.get("error_code"),
                           "checked_at":row["checked_at"],"next_try_at":row.get("next_try_at",row["checked_at"]),
                           "attempts":row.get("attempts",0)}])
        if "naver_auto_performance_job" in sql:
            return _Rows(self.jobs)
        if "naver_auto_manual_read" in sql:
            if "consumed_at IS NULL" in sql:
                return _Rows([row for row in self.requests if row.get("consumed_at") is None])
            if "WHERE" in sql:
                return _Rows([row for row in self.requests if row["customer_id"] == args[0]])
            return _Rows(self.requests)
        if "naver_auto_management_event" in sql:
            if "SELECT stage_key" in sql:
                return _Rows([{"stage_key": row.get("stage_key")} for row in self.events
                    if row["customer_id"] == args[0] and row["possibility_id"] == args[1]])
            keys = ("possibility_id", "at") if "WHERE customer_id" in sql else ("customer_id", "possibility_id")
            return _Rows([{key: row[key] for key in keys} for row in self.events
                          if not args or row["customer_id"] == args[0]])
        if "naver_auto_report_snapshot" in sql:
            return _Rows([])
        raise AssertionError("fixture에 없는 SQL")

    def account_catalog(self):
        return self.catalog

    def account_catalog_status(self):
        return {"state": self.catalog_state}

    def inventory_snapshot(self, now):
        return self.now

    def inventory_account_valid(self, customer_id, snapshot_at, now):
        S._customer_id(customer_id, "계정")
        return customer_id == TM.A and snapshot_at == self.now

    def accounts(self):
        return [{"customer_id": cid, "ad_account_no": 8_000_000+cid % 1_000_000,
                 "account_name": "가상 상점", "present": 1} for cid in self.states]

    def current_decisions(self):
        return []

    def org_current(self):
        return {"body": TA.org_body(self.now), "generated_at": self.now}

    def management_states(self):
        return self.states

    def decision_fingerprint(self):
        return "matching-1"

    def synchronize_management(self, now):
        from naver_engine import management_store as MS
        return MS.snapshot(self, now)

    def daily_performance(self, ids, start, end):
        return [row for row in self.daily_rows if row["customer_id"] in ids and str(start) <= row["day"] <= str(end)]

    def _need_writer(self):
        pass

    def _not_future(self, now, what):
        if now > self.now:
            raise S.StoreRefused("미래 시각")

    def performance_progress(self, job):
        return self.progress

    def report_snapshots(self):
        return [{"report_id": 1, "possibility_id": 11, "status": "ready"}]

    def _tx(self):
        raise AssertionError("잘못된 입력은 저장 경계에 도달하면 안 됩니다")


class ManagedStorageBoundaryTest(unittest.TestCase):
    """공개 메서드에 실제 정책·매칭을 통과시킨다. 로컬에서도 DB 없이 실행 가능."""
    def setUp(self):
        self.now = datetime(2026, 10, 5, 10, tzinfo=S.KST)
        self.st = _ManagedBoundary(self.now)

    def test_account_guard_fixture_projects_latest_matching_customer_in_both_tables(self):
        at = self.now.isoformat()
        self.st.jobs = [{"customer_id":TM.A,"status":"reauth_required","error_code":"KEY_REJECTED",
                         "checked_at":at,"next_try_at":at,"attempts":1},
                        {"customer_id":TM.B,"status":"ok","checked_at":at}]
        self.assertFalse(self.st.collection_account_ready(TM.A,self.now))
        self.assertTrue(self.st.collection_account_ready(TM.B,self.now))
        self.st.structure_jobs = [{"customer_id":TM.A,"status":"ok",
                                  "checked_at":(self.now+timedelta(seconds=1)).isoformat()}]
        self.assertTrue(self.st.collection_account_ready(TM.A,self.now+timedelta(seconds=1)))

    def test_two_unstarted_backfills_choose_one_account_without_comparing_dicts(self):
        job = self.st.performance_work(self.now, 1)[0]
        self.st.jobs = [{**job, "status": "ok", "attempts": 0, "checked_at": self.now.isoformat(),
                         "next_try_at": self.now.isoformat()}]
        jobs = self.st.performance_work(self.now, 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["kind"], "report_monthly")
        self.assertTrue(self.st.performance_account_valid(jobs[0], self.now))

    def test_tampered_job_shape_key_period_and_types_are_rejected_without_throwing(self):
        job = self.st.performance_work(self.now, 1)[0]
        self.assertTrue(self.st.performance_account_valid(job, self.now))
        for changes in ({"job_key": "different"}, {"period_start": "2026-10-03"},
                        {"cycle_day": "2026-10-04"}, {"period_end": "20261004"},
                        {"customer_id": True}, {"snapshot_at": self.now.replace(tzinfo=None)},
                        {"kind": "invented"}, {"conversion_tracking_confirmed": True}):
            with self.subTest(changes=changes):
                self.assertFalse(self.st.performance_account_valid({**job, **changes}, self.now))
        for value in (None, [], {}, {key: value for key, value in job.items() if key != "period_end"}):
            with self.subTest(value=value):
                self.assertFalse(self.st.performance_account_valid(value, self.now))

    def complete(self, job):
        day = job["period_start"]
        at = self.now.isoformat()
        self.st.progress = {"customer_id": TM.A, "period_start": day, "period_end": day,
                            "generation": job["generation"],
                            "campaign_ids": ["cmp-1"], "fingerprint": P.fingerprint(["cmp-1"]),
                            "next_index": 1, "cycles": [at], "conversion_evidence": True,
                            "day_totals": {day: dict(impCnt=10, clkCnt=1, salesAmt=100, ccnt=1, convAmt=200)}}
        return {"status": "ok", "campaign_fingerprint": P.fingerprint(["cmp-1"]),
                "daily_rows": [{"customer_id": TM.A, "day": day, "basic_complete": True,
                                "conversion_complete": True, "imp": 10, "clk": 1, "spend": 100,
                                "conversions": 1, "conversion_value": 200, "source_at": at, "checked_at": at}]}

    def test_completion_rejects_forged_or_future_evidence_before_transaction(self):
        job = self.st.performance_work(self.now, 1)[0]
        for changes in ({"source_at": None}, {"source_at": "not-a-time"},
                        {"source_at": (self.now+timedelta(seconds=1)).isoformat()},
                        {"source_at": (self.now-timedelta(seconds=1)).isoformat()},
                        {"checked_at": self.now.replace(tzinfo=None).isoformat()},
                        {"checked_at": (self.now+timedelta(seconds=1)).isoformat()},
                        {"checked_at": (self.now-timedelta(seconds=1)).isoformat()}, {"clk": True}):
            values = self.complete(job)
            values["daily_rows"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(S.StoreRefused):
                self.st.record_performance_check(job, self.now, values)
        values = self.complete(job)
        values["campaign_fingerprint"] = "other-campaigns"
        with self.assertRaises(S.StoreRefused):
            self.st.record_performance_check(job, self.now, values)

    def test_future_checkpoint_cycles_cannot_be_persisted(self):
        job = self.st.performance_work(self.now, 1)[0]
        self.complete(job)
        self.st.progress["cycles"] = [(self.now+timedelta(seconds=1)).isoformat()]
        with self.assertRaises(S.StoreRefused):
            self.st.record_performance_progress(job, self.now, self.st.progress)

    def test_successful_manual_collection_is_current_not_perpetually_pending(self):
        job = self.st.performance_work(self.now, 1)[0]
        self.st.jobs = [{**job, "kind": "manual", "status": "ok", "checked_at": self.now.isoformat(),
                         "error_code": None, "bizmoney": 1000, "bizmoney_at": self.now.isoformat(),
                         "possibility_id": 11}]
        current = self.st.performance_checks(self.now)[TM.A]
        self.assertEqual(current["status"], "ok")
        self.assertFalse(current["stale"])

    def test_direct_report_review_requires_fresh_catalog_and_visible_current_stage(self):
        for change in ("failed", "stale", "hidden", "unknown"):
            with self.subTest(change=change):
                self.st = _ManagedBoundary(self.now)
                if change == "failed":
                    self.st.catalog_state = "failed"
                elif change == "stale":
                    self.st.catalog["generated_at"] = (self.now-timedelta(days=2)).isoformat()
                elif change == "hidden":
                    self.st.catalog["items"][0]["stage_hidden"] = True
                else:
                    self.st.catalog["items"][0]["stage_known"] = False
                with self.assertRaises((S.StoreRefused, SC.ScopeError)):
                    self.st.record_report_review(1, 100, self.now, "approved", "확인")
                with self.assertRaises((S.StoreRefused, SC.ScopeError)):
                    self.st.performance_manual_request(TM.A, 100, self.now)

    def test_month_boundary_backfills_previous_closed_week_before_monthly_third(self):
        now = datetime(2026, 11, 2, 9, tzinfo=S.KST)
        self.st = _ManagedBoundary(now)
        daily = self.st.performance_work(now, 1)[0]
        self.st.jobs = [{**daily, "status": "ok", "attempts": 0, "checked_at": now.isoformat(),
                         "next_try_at": now.isoformat()}]
        job = self.st.performance_work(now, 1)[0]
        self.assertEqual((job["period_start"], job["period_end"]), ("2026-10-26", "2026-11-01"))
        self.assertTrue(self.st.performance_account_valid(job, now))
        self.st.daily_rows = [{"customer_id": TM.A, "possibility_id": 11, "day": day,
                               "basic_complete": True, "conversion_complete": True, "conversion_attempts": 0}
                              for day in ("2026-10-26", "2026-11-01")]
        job = self.st.performance_work(now, 1)[0]
        self.assertEqual((job["period_start"], job["period_end"]), ("2026-10-26", "2026-11-01"))
        self.assertTrue(self.st.performance_account_valid(job, now))

    def test_pending_manual_requests_do_not_fill_automatic_daily_batch(self):
        for pid, cid in ((12, TM.B), (13, TM.C_)):
            self.st.states[cid] = {**self.st.states[TM.A], "possibility_id": pid}
            self.st.catalog["items"].append({**self.st.catalog["items"][0], "possibility_id": pid})
            self.st.catalog["ids"].append({**self.st.catalog["ids"][0], "possibility_id": pid, "customer_id_raw": str(cid)})
        self.st.catalog["total"] = 3
        self.st.requests = [{"customer_id": cid, "requested_at": self.now.isoformat(), "actor": 0,
                             "possibility_id": self.st.states[cid]["possibility_id"]}
                            for cid in (TM.A, TM.B, TM.C_)]
        jobs = self.st.performance_work(self.now, 3)
        self.assertEqual([job["kind"] for job in jobs], ["manual", "daily", "daily"])

    def test_rematched_account_flags_legacy_data_even_without_current_success(self):
        self.st.events = [{"customer_id": TM.A, "possibility_id": pid, "at": self.now.isoformat()}
                          for pid in (11, 11, None, 12)]
        self.assertTrue(self.st.attribution_changes()[TM.A])
        self.assertTrue(self.st.performance_checks(self.now)[TM.A]["attribution_changed"])
        self.st.events.pop()
        self.assertFalse(self.st.attribution_changes()[TM.A])
        self.st.events.append({"customer_id": TM.A, "possibility_id": 11, "at": self.now.isoformat()})
        self.assertTrue(self.st.attribution_changes()[TM.A])

    def test_failed_same_job_recheck_preserves_success_and_compares_known_balances(self):
        job = self.st.performance_work(self.now, 1)[0]
        good_at = (self.now-timedelta(hours=2)).isoformat()
        before_at = (self.now-timedelta(hours=4)).isoformat()
        self.st.jobs = [{**job, "status": "retry", "checked_at": self.now.isoformat(), "error_code": "INCOMPLETE",
                         "possibility_id": 11, "bizmoney": None, "bizmoney_at": None,
                         "last_success_at": good_at, "last_bizmoney": 1000, "last_bizmoney_at": good_at,
                         "previous_bizmoney": 0, "previous_bizmoney_at": before_at}]
        self.st.daily_rows = [{"customer_id": TM.A, "possibility_id": 11, "day": job["period_end"],
                               "basic_complete": True, "spend": 100, "imp": 10, "clk": 1}]
        current = self.st.performance_checks(self.now)[TM.A]
        self.assertEqual((current["status"], current["stale"]), ("retry", True))
        self.assertEqual((current["spend"], current["last_success_at"]), (100, good_at))
        self.assertEqual((current["bizmoney"], current["previous_bizmoney"], current["bizmoney_change"]), (1000, 0, 1000))
        self.assertEqual(current["previous_bizmoney_at"], before_at)
        self.st.jobs[0]["previous_bizmoney"] = None
        self.assertIsNone(self.st.performance_checks(self.now)[TM.A]["bizmoney_change"])

    def test_daily_unknown_conversion_rechecks_only_after_two_hours_and_at_most_four(self):
        job = self.st.performance_work(self.now, 1)[0]
        checked = self.now-timedelta(hours=2)
        self.st.jobs = [{**job, "status": "ok", "attempts": 0, "checked_at": checked.isoformat(),
                         "next_try_at": self.now.isoformat()}]
        self.st.daily_rows = [{"customer_id": TM.A, "possibility_id": 11, "day": job["period_end"],
                               "basic_complete": True, "conversion_complete": False,
                               "conversion_attempts": 1, "checked_at": checked.isoformat()}]
        self.assertEqual(self.st.performance_work(self.now, 1)[0]["kind"], "daily")
        self.st.daily_rows[0]["checked_at"] = (checked+timedelta(seconds=1)).isoformat()
        self.assertFalse(any(row["kind"] == "daily" for row in self.st.performance_work(self.now, 24)))
        self.st.daily_rows[0].update(checked_at=checked.isoformat(), conversion_attempts=4)
        self.assertFalse(any(row["kind"] == "daily" for row in self.st.performance_work(self.now, 24)))

    def test_completed_nonmanaged_weekly_conversion_unknown_does_not_start_weekday_rechecks(self):
        sunday = datetime(2026, 10, 4, 8, tzinfo=S.KST)
        self.st = _ManagedBoundary(sunday)
        self.st.states[TM.A]["stage_key"] = "환불완료"
        self.st.catalog["items"][0]["stage"] = "환불 완료"
        job = self.st.performance_work(sunday, 1)[0]
        self.st.jobs = [{**job, "status": "ok", "attempts": 0, "checked_at": sunday.isoformat(),
                         "next_try_at": sunday.isoformat()}]
        self.st.daily_rows = [{"customer_id": TM.A, "possibility_id": 11, "day": job["period_end"],
                               "basic_complete": True, "conversion_complete": False,
                               "conversion_attempts": 1, "checked_at": sunday.isoformat()}]
        self.assertFalse(self.st.performance_work(sunday+timedelta(hours=2), 24))
        self.st.now = sunday+timedelta(days=1)
        self.st.catalog["generated_at"] = self.st.now.isoformat()
        self.assertFalse(self.st.performance_work(self.st.now, 24))


class ManagedStorageTest(TM.Base):
    def setUp(self):
        network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        network.start()
        self.addCleanup(network.stop)
        super().setUp()
        before = dict(TM.NAMES)
        TM.NAMES.update({TM.A: "가상에이상점", TM.B: "가상비상점", TM.C_: "가상씨상점"})
        self.addCleanup(lambda: (TM.NAMES.clear(), TM.NAMES.update(before)))
        self.items, self.identifiers = [], []
        self.naver = FakeNaver()
        self.campaign_count = 1
        self.metric = {"impCnt": 100, "clkCnt": 10, "salesAmt": 1000, "ccnt": 1, "convAmt": 2000}
        self.missing_days, self.day_overrides = set(), {}
        self.fail_stats = False
        self.naver.route(r"/ncc/campaigns", self.campaigns)
        self.naver.route(r"/billing/bizmoney", lambda call: (200, {"customerId": int(call.customer),
                         "bizmoney": 12000.5, "budgetLock": False, "refundLock": False}))
        self.naver.route(r"/stats", self.statistics)
        self.refresh()

    def campaigns(self, call):
        cid = int(call.customer)
        count = self.campaign_count if cid == TM.A else 0
        return 200, [{"customerId": cid, "nccCampaignId": f"cmp-{cid}-{n}", "status": "ELIGIBLE",
                      "userLock": False, "delFlag": False} for n in range(count)]

    def statistics(self, call):
        if self.fail_stats:
            return 200, {"cycleBaseTm": cycle_str(self.fc.now()), "data": []}
        span = json.loads(call.query["timeRange"][0])
        start, end = date.fromisoformat(span["since"]), date.fromisoformat(span["until"])
        if "ids" in call.query:
            self.assertEqual(start, end, "기간 합계를 날짜별 자료로 사용하지 않습니다")
            day = start.isoformat()
            rows = [] if day in self.missing_days else [
                {"id": cid, **self.metric, **self.day_overrides.get(day, {})} for cid in call.query["ids"]]
            return 200, {"cycleBaseTm": cycle_str(self.fc.now()), "data": rows}
        rows = []
        for offset in range((end-start).days+1):
            day = (start+timedelta(days=offset)).isoformat()
            if day not in self.missing_days:
                rows.append({"dateStart": day, **self.metric, **self.day_overrides.get(day, {})})
        return 200, {"cycleBaseTm": cycle_str(self.fc.now()), "data": rows}

    def save(self, items, ids=()):
        self.items, self.identifiers = deepcopy(items), tuple(ids)
        self.st.record_account_catalog({"generated_at": self.fc.now().isoformat(), "total": len(items),
                                        "complete": True, "items": items}, ids, self.fc.now())

    def refresh(self, when=None):
        if when is not None:
            self.fc.advance((when-self.fc.now()).total_seconds())
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.st.record_accounts(TM.kids(TM.A, TM.B, TM.C_), self.fc.now())
        self.save(self.items, self.identifiers)

    def managed(self, stage="진행중"):
        self.save([TC.company(11, stage, company_name=TM.NAMES[TM.A])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])

    def collect(self, **kwargs):
        return P.run_performance(self.reader(), self.st, self.fc.now, **kwargs)

    def confirmed_periods(self, when=None):
        self.refresh(when or datetime(2026, 10, 5, 10, tzinfo=S.KST))
        self.managed()
        self.st.record_decision(11, TM.A, "confirmed", 0, datetime(2026, 9, 1, 10, tzinfo=S.KST))
        self.assertEqual(self.collect().counts, {"ok": 1})
        self.assertEqual(self.collect().counts, {"ok": 1})
        self.assertEqual(self.collect().counts, {"ok": 1})

    def report(self, key="monthly:2026-09-01:2026-09-30"):
        return next(r for r in self.st.report_snapshots() if r["period_key"] == key)

    def revise_yesterday(self, values):
        self.fc.advance(3601)
        self.refresh()
        self.day_overrides[(self.fc.now().date()-timedelta(days=1)).isoformat()] = values
        self.st.performance_manual_request(TM.A, 100, self.fc.now())
        self.assertEqual(self.collect(limit=1).counts, {"ok": 1})

    def test_daily_stage_is_queued_but_unmatched_waits_for_sunday(self):
        self.managed()
        jobs = self.st.performance_work(self.fc.now(), 24)
        self.assertEqual([j["customer_id"] for j in jobs], [TM.A])
        job = jobs[0]
        self.assertEqual(job["kind"], "daily")
        self.assertEqual(job["period_start"], (self.fc.now().date()-timedelta(days=1)).isoformat())
        self.assertEqual(job["period_end"], job["period_start"])

    def test_exclusion_expires_when_stage_changes_and_never_resurrects(self):
        self.managed()
        self.st.synchronize_management(self.fc.now())
        first = self.st.management_states()[TM.A]["stage_revision"]
        self.st.record_management_override(TM.A, first, False, 0, self.fc.now(), "대표 확인")
        self.assertEqual(self.st.performance_work(self.fc.now(), 24)[0]["kind"], "daily")
        self.assertEqual(self.st.management_states()[TM.A]["excluded_revision"], first)
        self.fc.advance(1)
        self.managed("사후 관리")
        self.assertEqual(self.st.performance_work(self.fc.now(), 24)[0]["kind"], "daily")
        self.fc.advance(1)
        self.managed()
        self.assertEqual(self.st.performance_work(self.fc.now(), 24)[0]["kind"], "daily")
        with self.assertRaises(S.StoreRefused):
            self.st.record_management_override(TM.A, first, False, 0, self.fc.now(), "오래된 화면")

    def test_sunday_partial_weekly_job_resumes_monday_with_same_period_key(self):
        self.refresh(datetime(2026, 10, 4, 8, tzinfo=S.KST))
        self.managed("환불 완료")
        self.campaign_count = 9
        first = self.st.performance_work(self.fc.now(), 1)[0]
        self.assertEqual(self.collect(limit=1).counts, {"partial": 1})
        self.refresh(datetime(2026, 10, 5, 8, tzinfo=S.KST))
        resumed = self.st.performance_work(self.fc.now(), 1)[0]
        self.assertEqual(resumed["job_key"], first["job_key"])
        self.assertEqual((resumed["period_start"], resumed["period_end"]), ("2026-09-27", "2026-10-03"))
        self.assertEqual(self.collect(limit=1).counts, {"ok": 1})
        requests = [c.query["id"][0] for c in self.naver.calls if c.path == "/stats"]
        self.assertEqual(len(requests), len(set(requests)))
        self.assertFalse(self.st.performance_work(self.fc.now(), 24))

    def test_failed_new_day_preserves_last_success_and_its_actual_performance_date(self):
        self.managed()
        self.assertEqual(self.collect().counts, {"ok": 1})
        old = self.st.performance_checks(self.fc.now())[TM.A]
        old_day = date.fromisoformat(old["period_end"])
        saved = self.st.daily_performance([TM.A], old_day, old_day)
        self.refresh(self.fc.now()+timedelta(days=1))
        self.fail_stats = True
        self.assertEqual(self.collect().counts, {"source_wait": 1})
        current = self.st.performance_checks(self.fc.now())[TM.A]
        self.assertEqual(current["status"], "source_wait")
        self.assertTrue(current["stale"])
        self.assertEqual((current["period_end"], current["spend"]), (old["period_end"], old["spend"]))
        self.assertEqual(current["last_success_at"], old["last_success_at"])
        self.assertEqual(current["bizmoney_at"], old["bizmoney_at"])
        self.assertEqual(self.st.daily_performance([TM.A], old_day, old_day), saved)

    def test_conversion_downgrade_keeps_prior_evidence_in_history_not_current_roas(self):
        self.managed()
        self.collect()
        day = self.fc.now().date()-timedelta(days=1)
        self.revise_yesterday({"ccnt": None, "convAmt": None, "salesAmt": 1500})
        row = self.st.daily_performance([TM.A], day, day)[0]
        self.assertTrue(row["basic_complete"])
        self.assertFalse(row["conversion_complete"])
        self.assertIsNone(row["conversion_value"])
        self.assertEqual(row["spend"], 1500)
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as reader:
            history = reader.execute("SELECT payload_json FROM naver_auto_daily_revision WHERE customer_id=? AND day=?",
                                     (TM.A, day.isoformat())).fetchall()
        self.assertTrue(any(json.loads(r[0])["conversion_value"] == 2000 for r in history))

    def test_unknown_conversion_rechecks_are_spaced_and_stop_after_four(self):
        self.managed()
        self.metric.update(ccnt=None, convAmt=None)
        day = self.fc.now().date()-timedelta(days=1)
        for attempt in range(1, 5):
            if attempt > 1:
                self.fc.advance(2*3600)
                self.refresh()
            self.assertEqual(self.collect(limit=1).counts, {"ok": 1})
            row = self.st.daily_performance([TM.A], day, day)[0]
            self.assertEqual(row["conversion_attempts"], attempt)
            self.assertFalse(row["conversion_complete"])
            self.assertIsNone(row["conversion_value"])
            self.assertFalse(any(job["kind"] == "daily" for job in self.st.performance_work(self.fc.now())))
        self.fc.advance(2*3600)
        self.refresh()
        self.assertFalse(any(job["kind"] == "daily" for job in self.st.performance_work(self.fc.now())))

    def test_delayed_conversion_is_recollected_and_failed_recheck_keeps_success(self):
        self.managed()
        self.metric.update(ccnt=None, convAmt=None)
        self.assertEqual(self.collect(limit=1).counts, {"ok": 1})
        good = self.st.performance_checks(self.fc.now())[TM.A]
        self.fc.advance(2*3600)
        self.refresh()
        self.fail_stats = True
        self.assertEqual(self.collect(limit=1).counts, {"source_wait": 1})
        failed = self.st.performance_checks(self.fc.now())[TM.A]
        self.assertEqual((failed["last_success_at"], failed["spend"], failed["bizmoney"]),
                         (good["last_success_at"], good["spend"], good["bizmoney"]))
        self.fc.advance(15*60+1)
        self.refresh()
        self.fail_stats = False
        self.metric.update(ccnt=2, convAmt=4000)
        self.assertEqual(self.collect(limit=1).counts, {"ok": 1})
        day = self.fc.now().date()-timedelta(days=1)
        row = self.st.daily_performance([TM.A], day, day)[0]
        self.assertTrue(row["conversion_complete"])
        self.assertEqual(row["conversion_value"], 4000)

    def test_monthly_report_is_not_due_before_third_ten_and_month_end_missing_is_not_zero(self):
        self.refresh(datetime(2026, 10, 3, 9, 59, tzinfo=S.KST))
        self.managed()
        self.st.record_decision(11, TM.A, "confirmed", 0, self.fc.now())
        self.missing_days.add("2026-09-30")
        self.collect()
        self.collect()
        self.collect()
        self.st.generate_reports(self.fc.now())
        self.assertFalse(any(r["period_key"].startswith("monthly:2026-09") for r in self.st.report_snapshots()))
        self.fc.advance(70)
        self.st.generate_reports(self.fc.now())
        report = self.report()
        self.assertNotEqual(report["status"], "ready")
        self.assertIsNone(report["payload"]["totals"]["spend"])
        self.assertTrue(any(r["day"] == "2026-09-30" for r in report["payload"]["missing"]))
        with self.assertRaises(S.StoreRefused):
            self.st.record_report_review(report["report_id"], 100, self.fc.now(), "approved", "미완결 승인 금지")

    def test_report_is_idempotent_read_only_and_monthly_review_is_owner_scoped(self):
        self.confirmed_periods()
        calls = len(self.naver.calls)
        self.assertGreater(self.st.generate_reports(self.fc.now())["generated"], 0)
        self.assertEqual(self.st.generate_reports(self.fc.now())["generated"], 0)
        self.assertEqual(len(self.naver.calls), calls)
        report = self.report()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["review_status"], "needs_staff_review")
        with self.assertRaises(SC.ScopeError):
            self.st.record_report_review(report["report_id"], 101, self.fc.now(), "approved", "다른 담당")
        result = self.st.record_report_review(report["report_id"], 100, self.fc.now(), "approved", "원천 대조 완료")
        self.assertFalse(result["published"])
        self.assertEqual(self.report()["review_status"], "approved")

    def test_refunded_stage_preserves_existing_report_without_generating_new_ones(self):
        self.confirmed_periods()
        self.st.generate_reports(self.fc.now())
        previous = self.report()
        self.fc.advance(1)
        self.managed("환불 완료")
        self.assertEqual(self.st.generate_reports(self.fc.now())["generated"], 0)
        self.assertEqual(self.report()["report_id"], previous["report_id"])
        self.assertEqual(self.report()["status"], "ready")
        self.assertEqual(self.report()["payload"]["totals"]["spend"], 30000)

    def test_rematched_account_never_moves_saved_historical_performance_to_new_advertiser(self):
        self.confirmed_periods()
        self.st.generate_reports(self.fc.now())
        old = self.report()
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        self.assertTrue(all(row["possibility_id"] == 11 for row in self.st.daily_performance([TM.A], start, end)))
        self.fc.advance(1)
        self.save([TC.company(12, "진행중", company_name=TM.NAMES[TM.A])])
        self.st.record_decision(12, TM.A, "confirmed", 0, self.fc.now())
        for _ in range(3):
            self.assertEqual(self.collect(limit=1).counts, {"ok": 1})
        self.st.generate_reports(self.fc.now())
        reports = self.st.report_snapshots()
        new = next(row for row in reports if row["possibility_id"] == 12 and row["period_key"] == old["period_key"])
        self.assertNotEqual(new["status"], "ready")
        self.assertIsNone(new["payload"]["totals"]["spend"])
        self.assertFalse(self.st.daily_performance([TM.A], start, end, possibility_id=12))
        self.assertTrue(all(row["possibility_id"] == 11 for row in self.st.daily_performance([TM.A], start, end)))
        current = self.st.performance_checks(self.fc.now())[TM.A]
        self.assertTrue(current["attribution_changed"])
        self.assertIsNone(current["spend"])

    def test_same_period_rematch_discards_prior_campaign_checkpoint(self):
        self.managed()
        self.campaign_count = 9
        # 묶음 통계까지 읽고 최종 목록 확인 직전에 멈춰 체크포인트를 만든다.
        self.assertEqual(self.collect(limit=1, per_account_calls=3).counts, {"partial": 1})
        first_ids = [cid for call in self.naver.calls if call.path == "/stats"
                     for cid in call.query.get("ids", call.query.get("id", []))]
        self.assertTrue(first_ids)
        self.fc.advance(1)
        self.save([TC.company(12, "진행중", company_name=TM.NAMES[TM.A])])
        self.st.record_decision(12, TM.A, "confirmed", 0, self.fc.now())
        self.assertEqual(self.collect(limit=1, per_account_calls=3).counts, {"partial": 1})
        repeated = [cid for call in self.naver.calls if call.path == "/stats"
                    for cid in call.query.get("ids", call.query.get("id", []))][len(first_ids):]
        self.assertEqual(repeated, first_ids)

    def test_corrected_weekly_values_can_return_without_reusing_source_fingerprint_or_review(self):
        self.confirmed_periods()
        key = "weekly:2026-09-28:2026-10-04"
        self.st.generate_reports(self.fc.now())
        first = self.report(key)
        self.st.record_report_review(first["report_id"], 100, self.fc.now(), "approved", "초판 확인")
        self.revise_yesterday({"salesAmt": 2000})
        self.st.generate_reports(self.fc.now())
        second = self.report(key)
        self.assertNotEqual(second["report_id"], first["report_id"])
        self.assertIsNone(second["review"])
        with self.assertRaises(S.StoreRefused):
            self.st.record_report_review(first["report_id"], 100, self.fc.now(), "approved", "오래된 판")
        self.revise_yesterday({"salesAmt": 1000})
        self.st.generate_reports(self.fc.now())
        third = self.report(key)
        self.assertGreater(third["report_id"], second["report_id"])
        self.assertEqual(third["payload"]["totals"], first["payload"]["totals"])
        self.assertEqual(third["payload"]["ratios"], first["payload"]["ratios"])
        self.assertEqual(third["payload"]["details"]["daily"], first["payload"]["details"]["daily"])
        # 같은 숫자로 복귀해도 v2는 바뀐 원천 판의 증거를 지문에 고정한다.
        self.assertNotEqual(third["revision_fingerprint"], first["revision_fingerprint"])
        self.assertIsNone(third["review"])
        self.revise_yesterday({"salesAmt": 1000})
        self.st.generate_reports(self.fc.now())
        self.assertEqual(self.report(key)["report_id"], third["report_id"])

    def test_manual_request_has_owner_employment_and_one_hour_duplicate_guards(self):
        self.managed()
        with self.assertRaises(SC.ScopeError):
            self.st.performance_manual_request(TM.A, 101, self.fc.now())
        self.st.performance_manual_request(TM.A, 100, self.fc.now())
        with self.assertRaises(S.StoreRefused):
            self.st.performance_manual_request(TM.A, 100, self.fc.now())
        self.collect()
        with self.assertRaises(S.StoreRefused):
            self.st.performance_manual_request(TM.A, 100, self.fc.now())
        self.fc.advance(3601)
        self.refresh()
        accepted = self.st.performance_manual_request(TM.A, 100, self.fc.now())
        self.assertEqual(accepted["status"], "accepted")
        self.fc.advance(1)
        org = TA.org_body(self.fc.now())
        next(person for person in org["employees"] if person["idx"] == 100)["status"] = "RETIRED"
        self.st.record_org(org, self.fc.now())
        with self.assertRaises(SC.ScopeError):
            self.st.performance_manual_request(TM.A, 100, self.fc.now())
        before = len(self.naver.calls)
        day = self.fc.now().date()-timedelta(days=1)
        saved = self.st.daily_performance([TM.A], day, day)
        self.assertFalse(any(job["kind"] in ("manual", "manual_period")
                             for job in self.st.performance_work(self.fc.now())))
        # 퇴직한 요청자의 작업은 후보에서 제외한다. 다른 유효한 회차를 원천 오류로 막지 않는다.
        result = self.collect()
        self.assertEqual((result.code, result.counts), ("DONE", {}))
        self.assertEqual(len(self.naver.calls), before)
        self.assertEqual(self.st.daily_performance([TM.A], day, day), saved)
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as reader:
            self.assertEqual(reader.execute("""SELECT COUNT(*) FROM naver_auto_performance_job
                WHERE customer_id=? AND kind='manual' AND generation=?""",
                (TM.A, accepted["requested_at"])).fetchone()[0], 0)
            self.assertIsNone(reader.execute("""SELECT consumed_at FROM naver_auto_manual_read
                WHERE customer_id=? AND requested_at=?""",
                (TM.A, accepted["requested_at"])).fetchone()[0])

    def test_real_writer_proxy_runs_collection_and_returns_detached_daily_rows(self):
        from naver_runtime.writer import Writer
        self.managed()
        self.st.close()
        self.st = None
        with Writer(self.path, clock=self.fc.now) as writer:
            self.assertEqual(P.run_performance(self.reader(), writer.proxy, self.fc.now).counts, {"ok": 1})
            day = self.fc.now().date()-timedelta(days=1)
            rows = writer.proxy.daily_performance([TM.A], day, day)
            rows[0]["spend"] = 999999
            self.assertEqual(writer.proxy.daily_performance([TM.A], day, day)[0]["spend"], 1000)
