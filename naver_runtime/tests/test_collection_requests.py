"""요청 접수는 DB 공개 인터페이스의 독립 대역으로 시험한다(외부 연결 없음)."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import threading
from unittest import TestCase

from app.naver_auto import org_snapshot as O, scope as SC
from naver_engine import store as S, naver_read as N
from naver_engine.tests.fake_naver import FakeClock
from naver_engine.tests.test_sync import org_payload
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_runtime import collection_requests as CR


NOW = datetime(2026, 10, 1, 14, 0, tzinfo=S.KST)


class AuditStore:
    """저장소 공개 메서드의 작은 메모리 대역. 실제 SQLite 통합은 Linux에서 따로 시험한다."""
    def __init__(self):
        self.logs, self.runs = [], []
        self.audit_error = False
        self.holds = {}
        self.org = {"body": org_payload(NOW), "generated_at": NOW}

    def org_current(self):
        return deepcopy(self.org)

    def org_baseline(self):
        return None

    def record_org(self, body, at, **kwargs):
        self.org = {"body": deepcopy(body), "generated_at": datetime.fromisoformat(body["generated_at"])}

    def hold(self, kind):
        return deepcopy(self.holds.get(kind))

    def record_access(self, viewer_idx, action, target_kind, target_id, result, at):
        if self.audit_error:
            raise S.StoreError("SECRET_MARKER")
        row = dict(log_id=len(self.logs) + 1, emp_idx=viewer_idx, action=action,
                   target_kind=target_kind, target_id=target_id, result=result, at=at.isoformat())
        self.logs.append(row)
        return row["log_id"]

    def access_log(self, limit=100, viewer_idx=None):
        rows = [r for r in reversed(self.logs) if viewer_idx is None or r["emp_idx"] == viewer_idx]
        return deepcopy(rows[:limit])

    def runs_on(self, day):
        return deepcopy(self.runs)


def enabled():
    return Config("/synthetic/data/db", "/synthetic/socket/sock", sync_enabled=True,
                  links_enabled=True, morning_enabled=True, web_enabled=True)


class CollectionRequestTest(TestCase):
    def test_current_owner_role_is_not_a_hardcoded_employee_id(self):
        cases = (("owner", 0, {}), ("nonzero_owner", 1, {"is_top_manager": True}),
                 ("resigned_owner", 0, {"status": "RESIGNED"}), ("leader", 1, {}),
                 ("staff", 100, {}), ("unknown", 999999, {}))
        for role, actor, changes in cases:
            with self.subTest(role=role):
                store = AuditStore()
                for person in store.org["body"]["employees"]:
                    if person["idx"] == actor:
                        person.update(changes)
                is_all = SC.scope_of(O.parse_org_snapshot(store.org["body"]), actor).kind == SC.ALL
                self.assertEqual(CR.owner_allowed(store, actor, NOW), is_all)
                task = Scheduler(enabled(), store, collection_factory=lambda: None, clock=lambda: NOW)
                self.assertEqual(task.request_collection(actor)["status"], "accepted" if is_all else "refused")

    def test_concurrent_tick_and_requests_cannot_create_a_second_reader(self):
        store, entered, release = AuditStore(), threading.Event(), threading.Event()
        reads = []
        class Reader:
            calls = 0
            def read_org_snapshot(self):
                reads.append("org")
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("시험 대기 종료")
                raise RuntimeError("합성 외부 실패")
        task = Scheduler(enabled(), store, clock=lambda: NOW, collection_factory=lambda:
                         dict(clock=CR.CollectionClock(FakeClock(NOW)), erp_factory=Reader))
        task.request_collection(0)
        worker = threading.Thread(target=task.tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(task.collection_status()["status"], "running")
            self.assertEqual(task.request_collection(0)["status"], "busy")
            self.assertEqual(task.tick(), {"state": "busy"})
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(reads, ["org"])

    def test_expired_queue_and_new_scheduled_run_refuse_before_readers(self):
        for mode in ("expired", "run"):
            with self.subTest(mode=mode):
                store, at = AuditStore(), [NOW]
                task = Scheduler(enabled(), store, clock=lambda: at[0],
                                 collection_factory=lambda: self.fail("만료·재시도 대기 중 외부 읽기 금지"))
                task.request_collection(0)
                if mode == "expired":
                    at[0] += timedelta(minutes=11)
                else:
                    store.runs = [{"status": S.RUN_DONE, "finished_at": NOW.isoformat()}]
                task.tick()
                self.assertEqual(task.collection_status()["codes"],
                                 ["REQUEST_EXPIRED" if mode == "expired" else "RETRY_NOT_DUE"])

    def test_restart_reports_interruption_without_replaying_queued_request(self):
        store = AuditStore()
        factory = lambda: self.fail("재시작 후 자동 재생 금지")
        first = Scheduler(enabled(), store, collection_factory=factory, clock=lambda: NOW)
        request = first.request_collection(0)
        restarted = Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock"), store,
                              collection_factory=factory, clock=lambda: NOW)
        self.assertEqual(restarted.collection_status(),
                         {"id": request["id"], "status": "failed", "codes": ["PROCESS_RESTARTED_NOT_REPLAYED"]})
        self.assertEqual(restarted.tick(), {"state": "ok", "errors": []})
        self.assertEqual(len(store.logs), 1)

    def test_pending_hold_is_not_refreshed_or_confirmed(self):
        store = AuditStore()
        store.holds[S.SYNC_STAGES] = {"at": NOW, "used_at": None}
        task = Scheduler(enabled(), store, clock=lambda: NOW, collection_factory=lambda:
                         dict(clock=CR.CollectionClock(FakeClock(NOW)),
                              erp_factory=lambda: self.fail("확인 대기 원본 덮어쓰기 금지")))
        task.request_collection(0)
        task.tick()
        self.assertEqual(task.collection_status()["codes"], ["HOLD_PENDING"])

    def test_freshly_demoted_owner_stops_before_naver_or_stage_reads(self):
        store, reads = AuditStore(), []
        store.org["body"]["employees"][1]["is_top_manager"] = True
        body = deepcopy(store.org["body"])
        body["generated_at"] = (NOW + timedelta(seconds=1)).isoformat()
        body["employees"][0]["is_top_manager"] = False
        class Reader:
            calls = 0
            def read_org_snapshot(self):
                reads.append("org")
                return body
        task = Scheduler(enabled(), store, clock=lambda: NOW, collection_factory=lambda:
                         dict(clock=CR.CollectionClock(FakeClock(NOW)), erp_factory=Reader,
                              naver_factory=lambda: self.fail("강등 뒤 네이버 읽기 금지")))
        self.assertEqual(task.request_collection(0)["status"], "accepted")
        task.tick()
        self.assertEqual(task.collection_status()["codes"], ["OWNER_REQUIRED"])
        self.assertEqual(reads, ["org"])

    def test_fresh_org_is_followed_by_stage_refresh_without_reusing_reader(self):
        store, reads = AuditStore(), []
        body = org_payload(NOW + timedelta(seconds=1))
        class Reader:
            def __init__(self):
                self.calls = 0
            def read_org_snapshot(self):
                reads.append("org")
                self.calls += 1
                return body
            def read_stages(self, deadline=None):
                reads.append("stages")
                raise RuntimeError("SECRET_MARKER")
        task = Scheduler(enabled(), store, clock=lambda: NOW, collection_factory=lambda:
                         dict(clock=CR.CollectionClock(FakeClock(NOW)), erp_factory=Reader,
                              naver_factory=lambda: self.fail("단계 실패 뒤 네이버 읽기 금지")))
        task.request_collection(0)
        task.tick()
        self.assertEqual(task.collection_status()["status"], "failed")
        self.assertEqual(reads, ["org", "stages"])

    def test_tick_consumes_once_and_audits_failure_without_secret(self):
        store, reads = AuditStore(), []
        class Reader:
            calls = 0
            def read_org_snapshot(self):
                reads.append("org")
                raise RuntimeError("SECRET_MARKER")
        def factory():
            return dict(clock=CR.CollectionClock(FakeClock(NOW)), erp_factory=Reader,
                        naver_factory=lambda: self.fail("조직 갱신 실패 뒤 네이버 읽기 금지"))
        task = Scheduler(enabled(), store, collection_factory=factory, clock=lambda: NOW)
        request = task.request_collection(0)
        self.assertEqual(task.tick(), {"state": "failed", "errors": ["collection"]})
        result = task.collection_status()
        self.assertEqual((result["id"], result["status"], reads), (request["id"], "failed", ["org"]))
        self.assertNotIn("SECRET_MARKER", repr(result))
        self.assertEqual([r["result"] for r in store.access_log()], ["failed", "started", "accepted"])

    def test_execution_audit_failure_performs_no_external_reads(self):
        store = AuditStore()
        task = Scheduler(enabled(), store, collection_factory=lambda: self.fail("감사 실패 뒤 외부 읽기 금지"),
                         clock=lambda: NOW)
        task.request_collection(0)
        store.audit_error = True
        self.assertEqual(task.tick(), {"state": "failed", "errors": ["collection"]})
        self.assertEqual(task.collection_status()["codes"], ["AUDIT_UNAVAILABLE"])

    def test_collection_clock_caps_waits_and_keeps_real_time_for_cleanup(self):
        base = FakeClock(NOW)
        clock = CR.CollectionClock(base, seconds=10)
        self.assertEqual(clock.now(), NOW)
        self.assertEqual(clock.remaining(), 10)
        with self.assertRaises(N.RunAbort):
            clock.sleep(100)
        self.assertEqual(clock.now(), NOW + timedelta(seconds=10))
        with self.assertRaises(N.RunAbort):
            clock.before_network()
        for seconds in (0, 601, True):
            with self.assertRaises(ValueError):
                CR.CollectionClock(base, seconds=seconds)

    def test_network_timeout_cannot_outlive_collection_budget(self):
        from naver_runtime.__main__ import StopAwareTransport
        base, timeouts = FakeClock(NOW), []
        clock = CR.CollectionClock(base, seconds=2)
        class Transport:
            def send(self, request, timeout):
                timeouts.append(timeout)
                return "synthetic"
        transport = StopAwareTransport(clock, Transport())
        self.assertEqual(transport.send("synthetic", 20), "synthetic")
        self.assertEqual(timeouts, [2])
        base.advance(2)
        with self.assertRaises(N.RunAbort):
            transport.send("synthetic", 20)
        self.assertEqual(timeouts, [2])

    def test_non_owner_stale_org_and_unrestricted_config_are_refused(self):
        for actor in (True, -1, "0", 1, 100):
            with self.subTest(actor=actor):
                store = AuditStore()
                task = Scheduler(enabled(), store, collection_factory=lambda: None, clock=lambda: NOW)
                self.assertEqual(task.request_collection(actor)["codes"], ["OWNER_REQUIRED"])
                self.assertEqual(store.logs, [])
        store = AuditStore()
        store.org["generated_at"] = NOW - timedelta(hours=27)
        task = Scheduler(enabled(), store, collection_factory=lambda: None, clock=lambda: NOW)
        self.assertEqual(task.request_collection(0)["codes"], ["OWNER_REQUIRED"])
        for config in (replace(enabled(), sync_enabled=False), replace(enabled(), alerts_enabled=True),
                       replace(enabled(), metrics_enabled=True), replace(enabled(), issue_alerts_enabled=True)):
            task = Scheduler(config, AuditStore(), collection_factory=lambda: None, clock=lambda: NOW)
            self.assertEqual(task.request_collection(0)["codes"], ["RESTRICTED_CONFIG_REQUIRED"])

    def test_acceptance_is_durable_singleton_and_does_not_create_readers(self):
        store = AuditStore()
        def no_network():
            self.fail("접수 중 외부 읽기 금지")
        scheduler = Scheduler(enabled(), store, collection_factory=no_network, clock=lambda: NOW)
        result = scheduler.request_collection(0)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["id"], store.access_log()[0]["log_id"])
        self.assertEqual(store.access_log()[0]["action"], "collection_request")
        self.assertEqual(scheduler.request_collection(0)["status"], "busy")
        self.assertEqual(scheduler.collection_status(), result)
        result["codes"].append("changed")
        self.assertEqual(scheduler.collection_status()["codes"], [])

    def test_audit_failure_refuses_without_queueing_or_disclosing_error(self):
        store = AuditStore()
        store.audit_error = True
        task = Scheduler(enabled(), store, collection_factory=lambda: None, clock=lambda: NOW)
        self.assertEqual(task.request_collection(0),
                         {"id": None, "status": "refused", "codes": ["AUDIT_UNAVAILABLE"]})
        self.assertEqual(task.collection_status()["status"], "idle")

    def test_global_cooldown_and_daily_limits_survive_new_scheduler(self):
        store = AuditStore()
        task = lambda at: Scheduler(enabled(), store, collection_factory=lambda: None, clock=lambda: at)
        store.record_access(7, "collection_request", "board", None, "accepted", NOW - timedelta(minutes=19))
        self.assertEqual(task(NOW).request_collection(0)["codes"], ["RETRY_NOT_DUE"])
        self.assertEqual(task(NOW + timedelta(minutes=1)).request_collection(0)["status"], "accepted")
        self.assertEqual(task(NOW + timedelta(minutes=21)).request_collection(0)["status"], "accepted")
        self.assertEqual(task(NOW + timedelta(minutes=41)).request_collection(0)["codes"], ["RUNS_EXHAUSTED"])

    def test_normal_morning_run_limits_also_gate_immediate_preparation(self):
        store = AuditStore()
        task = lambda: Scheduler(enabled(), store, collection_factory=lambda: None, clock=lambda: NOW)
        store.runs = [{"status": S.RUN_DONE, "finished_at": (NOW - timedelta(minutes=19)).isoformat()}]
        self.assertEqual(task().request_collection(0)["codes"], ["RETRY_NOT_DUE"])
        store.runs = [{"status": S.RUN_DONE, "finished_at": (NOW - timedelta(hours=1)).isoformat()}] * 3
        self.assertEqual(task().request_collection(0)["codes"], ["RUNS_EXHAUSTED"])
