"""SQLite 연결을 만든 스레드 한 곳에서만 저장한다.

예약 작업의 외부 조회는 이 스레드 밖에서 수행한다. 큐에서 기다리다 취소된
화면 요청은 나중에 실행하지 않는다. 실행을 시작한 짧은 DB 작업은 결과까지 받는다.
"""
from concurrent.futures import Future, TimeoutError
from queue import Empty, Full, Queue
import threading
from time import monotonic
from types import MappingProxyType

from naver_engine import store as S


# 예약 작업이 호출할 수 있는 공개 저장소 메서드만. 연결/경로/잠금은 노출하지 않는다.
METHODS = frozenset("""
account_day_marks_on account_days_on account_times accounts accounts_read_at
alert_recipients alerts_on begin_run close_unlinked_issues decision_fingerprint
due_deliveries finish_run heartbeat hold issue_event_counts_on issues last_pairing
last_sync link_decisions matched_before my_running_runs org_baseline org_current
pairing_rows pairing_run prospects record_account_check record_accounts record_alert
record_delivery record_heartbeat record_org record_pairing record_pairing_event
record_prospects record_sync_event refuse_org refuse_stages runs_on stage_as_of
system_alert_keys_on thresholds snapshot_to
metrics_context metrics_work begin_metrics_attempt record_metrics_snapshot metrics_payload
finish_metrics_attempt record_access access_log
account_catalog_status record_account_catalog record_account_catalog_failure
inventory_snapshot inventory_account_valid inventory_work begin_inventory_check
collection_account_ready
inventory_progress record_inventory_progress record_inventory_check
monthly_checks_on monthly_work begin_monthly_check monthly_progress record_monthly_progress record_monthly_check
account_catalog current_decisions management_states synchronize_management record_management_override
automatic_link_evidence
morning_progress begin_morning_progress record_morning_progress finish_morning_progress
performance_work performance_account_valid begin_performance_check performance_progress
record_performance_progress record_performance_check daily_performance performance_checks
performance_manual_request generate_reports report_snapshots report_history record_report_review
latest_inventory_successes observed_campaign_reasons
attribution_changes
structure_work structure_account_valid begin_structure_check structure_progress record_structure_progress
record_structure_check structure_checks structure_reason_summaries structure_reason_page
""".split())


# 공개 진단에는 호출 이름/인수를 내보내지 않는다. 기존 proxy의 고정 메서드만
# 명시한 번호로 식별한다. 새 메서드를 추가해도 기존 번호를 재배정하지 않는다.
PHASE_UNKNOWN = 0
PHASE_WEB_WRITE = 104
DIAGNOSTIC_PHASE_IDS = MappingProxyType({
    "access_log": 1,
    "account_catalog": 2,
    "account_catalog_status": 3,
    "account_day_marks_on": 4,
    "account_days_on": 5,
    "account_times": 6,
    "accounts": 7,
    "accounts_read_at": 8,
    "alert_recipients": 9,
    "alerts_on": 10,
    "attribution_changes": 11,
    "automatic_link_evidence": 12,
    "begin_inventory_check": 13,
    "begin_metrics_attempt": 14,
    "begin_monthly_check": 15,
    "begin_morning_progress": 16,
    "begin_performance_check": 17,
    "begin_run": 18,
    "begin_structure_check": 19,
    "close_unlinked_issues": 20,
    "collection_account_ready": 21,
    "current_decisions": 22,
    "daily_performance": 23,
    "decision_fingerprint": 24,
    "due_deliveries": 25,
    "finish_metrics_attempt": 26,
    "finish_morning_progress": 27,
    "finish_run": 28,
    "generate_reports": 29,
    "heartbeat": 30,
    "hold": 31,
    "inventory_account_valid": 32,
    "inventory_progress": 33,
    "inventory_snapshot": 34,
    "inventory_work": 35,
    "issue_event_counts_on": 36,
    "issues": 37,
    "last_pairing": 38,
    "last_sync": 39,
    "latest_inventory_successes": 40,
    "link_decisions": 41,
    "management_states": 42,
    "matched_before": 43,
    "metrics_context": 44,
    "metrics_payload": 45,
    "metrics_work": 46,
    "monthly_checks_on": 47,
    "monthly_progress": 48,
    "monthly_work": 49,
    "morning_progress": 50,
    "my_running_runs": 51,
    "observed_campaign_reasons": 52,
    "org_baseline": 53,
    "org_current": 54,
    "pairing_rows": 55,
    "pairing_run": 56,
    "performance_account_valid": 57,
    "performance_checks": 58,
    "performance_manual_request": 59,
    "performance_progress": 60,
    "performance_work": 61,
    "prospects": 62,
    "record_access": 63,
    "record_account_catalog": 64,
    "record_account_catalog_failure": 65,
    "record_account_check": 66,
    "record_accounts": 67,
    "record_alert": 68,
    "record_delivery": 69,
    "record_heartbeat": 70,
    "record_inventory_check": 71,
    "record_inventory_progress": 72,
    "record_management_override": 73,
    "record_metrics_snapshot": 74,
    "record_monthly_check": 75,
    "record_monthly_progress": 76,
    "record_morning_progress": 77,
    "record_org": 78,
    "record_pairing": 79,
    "record_pairing_event": 80,
    "record_performance_check": 81,
    "record_performance_progress": 82,
    "record_prospects": 83,
    "record_report_review": 84,
    "record_structure_check": 85,
    "record_structure_progress": 86,
    "record_sync_event": 87,
    "refuse_org": 88,
    "refuse_stages": 89,
    "report_history": 90,
    "report_snapshots": 91,
    "runs_on": 92,
    "snapshot_to": 93,
    "stage_as_of": 94,
    "structure_account_valid": 95,
    "structure_checks": 96,
    "structure_progress": 97,
    "structure_reason_page": 98,
    "structure_reason_summaries": 99,
    "structure_work": 100,
    "synchronize_management": 101,
    "system_alert_keys_on": 102,
    "thresholds": 103,
})
_DIAGNOSTIC_PHASES = frozenset((PHASE_UNKNOWN, PHASE_WEB_WRITE, *DIAGNOSTIC_PHASE_IDS.values()))


class _StoreProxy:
    def __init__(self, writer):
        self._writer = writer

    def __getattr__(self, name):
        if name not in METHODS:
            raise AttributeError("허용한 저장소 메서드가 아닙니다")
        return lambda *args, **kwargs: self._writer.call(
            lambda st: getattr(st, name)(*args, **kwargs), _phase=DIAGNOSTIC_PHASE_IDS[name])


class Writer:
    def __init__(self, path, *, clock=None, factory=S.open_writer, capacity=32):
        self._queue = Queue(maxsize=capacity)
        self._stopping = threading.Event()
        self._diagnostic_lock = threading.Lock()
        self._diagnostic_counts = dict(accepted=0, completed=0, queued_cancel=0, full=0, closed=0, error=0)
        self._active_started = None
        self._active_phase = PHASE_UNKNOWN
        self._last_completed_phase = PHASE_UNKNOWN
        self._ready = Future()
        self._thread = threading.Thread(target=self._run, args=(factory, path, clock),
                                        name="naver-store", daemon=True)
        self.proxy = _StoreProxy(self)
        self._thread.start()
        try:
            self._ready.result(timeout=15)
        except BaseException:
            self._stopping.set()
            raise

    def _run(self, factory, path, clock):
        store = None
        try:
            store = factory(path, clock=clock)
            self._ready.set_result(True)
            while not self._stopping.is_set():
                try:
                    future, fn = self._queue.get(timeout=.1)
                except Empty:
                    continue
                if future.set_running_or_notify_cancel():
                    with self._diagnostic_lock:
                        self._active_started = monotonic()
                        self._active_phase = future._diagnostic_phase
                    try:
                        future.set_result(fn(store))
                    except BaseException as exc:
                        with self._diagnostic_lock:
                            self._diagnostic_counts["error"] += 1
                        future.set_exception(exc)
                    finally:
                        with self._diagnostic_lock:
                            self._diagnostic_counts["completed"] += 1
                            self._last_completed_phase = self._active_phase
                            self._active_started = None
                            self._active_phase = PHASE_UNKNOWN
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            self._stopping.set()
            if store is not None:
                store.close()
            while True:
                try:
                    pending, _ = self._queue.get_nowait()
                    if pending.cancel():
                        self._count_queued_cancel(pending)
                except Empty:
                    break

    def diagnostics(self):
        """수동 관측용 숫자만 복사한다. DB/FIFO/콜백 이름/인수에 접근하지 않는다.

        completed는 실행을 마친 콜백(오류 포함), queued_cancel은 실행 전에
        취소된 항목(대기 초과와 종료)을 항목당 한 번 센다. 재설정하지 않는다.
        """
        with self._diagnostic_lock:
            with self._queue.mutex:
                depth = len(self._queue.queue)
            busy_ms = 0 if self._active_started is None else max(0, int((monotonic()-self._active_started)*1000))
            return {"queue_depth": depth, "busy_duration_ms": busy_ms,
                    "active_phase": self._active_phase,
                    "last_completed_phase": self._last_completed_phase,
                    **self._diagnostic_counts}

    def _count_queued_cancel(self, future):
        with self._diagnostic_lock:
            if not future._diagnostic_cancel_counted:
                future._diagnostic_cancel_counted = True
                self._diagnostic_counts["queued_cancel"] += 1

    def _discard_cancelled(self, item):
        # Queue에는 대기 항목 제거 API가 없다. get/put과 같은 잠금에서 제거한다.
        with self._queue.mutex:
            try:
                self._queue.queue.remove(item)
            except ValueError:
                return  # 소비자나 종료 처리가 이미 가져간 항목이다.
            self._queue.not_full.notify()

    def call(self, fn, *, wait=15, _phase=PHASE_UNKNOWN):
        if threading.get_ident() == self._thread.ident:
            raise S.StoreRefused("저장 작업 안에서 다시 예약하지 않습니다")
        if type(_phase) is not int or _phase not in _DIAGNOSTIC_PHASES:
            raise S.StoreRefused("저장 진단 단계가 올바르지 않습니다")
        future = Future()
        future._diagnostic_phase = _phase
        future._diagnostic_cancel_counted = False
        item = (future, fn)
        with self._diagnostic_lock:
            if self._stopping.is_set() or not self._thread.is_alive():
                self._diagnostic_counts["closed"] += 1
                raise S.StoreBusy("저장 연결이 닫혀 있습니다")
            try:
                self._queue.put_nowait(item)
            except Full:
                self._diagnostic_counts["full"] += 1
                raise S.StoreBusy("저장 요청이 많습니다") from None
            self._diagnostic_counts["accepted"] += 1
        try:
            return future.result(timeout=wait)
        except TimeoutError:
            if future.cancel():
                self._count_queued_cancel(future)
                self._discard_cancelled(item)
                raise S.StoreBusy("저장 대기 시간을 넘었습니다") from None
            # 이미 시작한 저장의 결과를 모른 채 실패라고 답하지 않는다.
            return future.result()

    def close(self):
        self._stopping.set()
        self._thread.join(15)
        if self._thread.is_alive():
            raise S.StoreBusy("진행 중인 저장 작업의 종료를 확인하지 못했습니다")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
