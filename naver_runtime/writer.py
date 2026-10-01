"""SQLite 연결을 만든 스레드 한 곳에서만 저장한다.

예약 작업의 외부 조회는 이 스레드 밖에서 수행한다. 큐에서 기다리다 취소된
화면 요청은 나중에 실행하지 않는다. 실행을 시작한 짧은 DB 작업은 결과까지 받는다.
"""
from concurrent.futures import Future, TimeoutError
from queue import Empty, Full, Queue
import threading

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
""".split())


class _StoreProxy:
    def __init__(self, writer):
        self._writer = writer

    def __getattr__(self, name):
        if name not in METHODS:
            raise AttributeError("허용한 저장소 메서드가 아닙니다")
        return lambda *args, **kwargs: self._writer.call(lambda st: getattr(st, name)(*args, **kwargs))


class Writer:
    def __init__(self, path, *, clock=None, factory=S.open_writer, capacity=32):
        self._queue = Queue(maxsize=capacity)
        self._stopping = threading.Event()
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
                    try:
                        future.set_result(fn(store))
                    except BaseException as exc:
                        future.set_exception(exc)
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
                    pending.cancel()
                except Empty:
                    break

    def call(self, fn, *, wait=15):
        if threading.get_ident() == self._thread.ident:
            raise S.StoreRefused("저장 작업 안에서 다시 예약하지 않습니다")
        if self._stopping.is_set() or not self._thread.is_alive():
            raise S.StoreBusy("저장 연결이 닫혀 있습니다")
        future = Future()
        try:
            self._queue.put_nowait((future, fn))
        except Full:
            raise S.StoreBusy("저장 요청이 많습니다") from None
        try:
            return future.result(timeout=wait)
        except TimeoutError:
            if future.cancel():
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
