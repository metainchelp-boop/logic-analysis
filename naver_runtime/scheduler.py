"""기존 부를 때 판정들을 한 회차로 연결한다. 네이버 쓰기는 없다."""
from datetime import datetime, time, timedelta
from copy import deepcopy
import logging
import threading
from time import monotonic

from naver_engine import alerts as A, links as L, morning as M, store as S, sync as Y, metrics as G, naver_read as N
from naver_engine import inventory as IC, performance_reads as PR, management_store as MS, structure_reads as SR
from naver_runtime import collection_requests as CR

log = logging.getLogger("naver_runtime.scheduler")


class _ManagedMorningStore:
    """자동 아침 상세 점검도 실관리 대상만 읽게 한다. 이관 부재 판정은 유지한다."""
    def __init__(self, store, now):
        self.store = store
        self.daily = {cid for cid,row in MS.snapshot(store,now).items() if row["decision"].cadence == "daily"}
        # 동적 메서드 노출 없이 아침 읽기/판정에서 사용하는 공개 계약만 전달한다.
        self.account_day_marks_on = store.account_day_marks_on
        self.account_days_on = store.account_days_on
        self.accounts_read_at = store.accounts_read_at
        self.begin_run = store.begin_run
        self.close_unlinked_issues = store.close_unlinked_issues
        self.decision_fingerprint = store.decision_fingerprint
        self.finish_run = store.finish_run
        self.issues = store.issues
        self.last_pairing = store.last_pairing
        self.last_sync = store.last_sync
        self.my_running_runs = store.my_running_runs
        self.prospects = store.prospects
        self.record_account_check = store.record_account_check
        self.runs_on = store.runs_on
        self.stage_as_of = store.stage_as_of

    def pairing_rows(self, pairing_id):
        return [r for r in self.store.pairing_rows(pairing_id)
                if r.get("customer_id") in self.daily or r["state"] in (S.PAIR_BROKEN,S.PAIR_MISSING)]


class Scheduler:
    def __init__(self, config, store, *, erp_factory=None, naver_factory=None,
                 alert_factory=None, metrics_factory=None, clock=None, backup_job=None,
                 collection_factory=None, monotonic_clock=None):
        self.config, self.store = config, store
        self.erp_factory, self.naver_factory = erp_factory, naver_factory
        self.alert_factory, self.backup_job = alert_factory, backup_job
        self.metrics_factory = metrics_factory
        self.collection_factory = collection_factory
        self.clock = clock or (lambda: datetime.now(S.KST))
        self._monotonic = monotonic_clock or monotonic
        self.policy = A.AlertPolicy(config.issue_alerts_from, config.issue_alerts_enabled)
        self._lock = threading.Lock()
        self._last = {}
        self._next_steps = {}
        self._inventory_ready_at = 0.0
        self._naver_rate_ready_at = 0.0
        self.last_tick = None
        self.last_errors = ()
        self._collection_lock = threading.Lock()
        self._collection_pending = None
        self._collection_latest = None

    def request_collection(self, actor):
        """대표 화면에서 검증한 요청을 접수만 한다. 네트워크는 tick에서만 실행한다."""
        with self._collection_lock:
            if self.collection_factory is None or not CR.restricted(self.config):
                return CR.refused("RESTRICTED_CONFIG_REQUIRED")
            try:
                if not CR.owner_allowed(self.store, actor, self.clock()):
                    return CR.refused("OWNER_REQUIRED")
                if self._collection_latest and self._collection_latest["status"] in ("accepted", "running"):
                    return dict(deepcopy(self._collection_latest), status="busy", codes=["COLLECTION_BUSY"])
                code = CR.request_limit(self.store, self.clock())
                if code:
                    return CR.refused(code)
                requested_at = self.clock()
                request_id = self.store.record_access(actor, "collection_request", "board", None,
                                                       "accepted", requested_at)
            except Exception:
                return CR.refused("AUDIT_UNAVAILABLE")
            self._collection_pending = (request_id, actor, requested_at)
            self._collection_latest = {"id": request_id, "status": "accepted", "codes": []}
            return deepcopy(self._collection_latest)

    def collection_status(self):
        with self._collection_lock:
            if self._collection_latest is None and self.collection_factory is not None:
                try:
                    return CR.recovered_status(self.store)
                except Exception:
                    return {"id": None, "status": "failed", "codes": ["AUDIT_UNAVAILABLE"]}
            return deepcopy(self._collection_latest or {"id": None, "status": "idle", "codes": []})

    def _run_collection(self):
        with self._collection_lock:
            if self._collection_pending is None:
                return False
            request_id, actor, requested_at = self._collection_pending
            self._collection_pending = None
            self._collection_latest = {"id": request_id, "status": "running", "codes": []}
        result = {"status": "failed", "codes": ["AUDIT_UNAVAILABLE"]}
        try:
            self.store.record_access(actor, "collection_run", "board", request_id, "started", self.clock())
            if not CR.restricted(self.config):
                result = CR.refused("RESTRICTED_CONFIG_REQUIRED")
            elif not CR.owner_allowed(self.store, actor, self.clock()):
                result = CR.refused("OWNER_REQUIRED")
            elif (self.clock() - requested_at >= timedelta(minutes=10)
                  or self.clock().astimezone(S.KST).date() != requested_at.astimezone(S.KST).date()):
                result = CR.refused("REQUEST_EXPIRED")
            else:
                code = CR.request_limit(self.store, self.clock(), exclude_id=request_id)
                result = CR.refused(code) if code else CR.collect(self.store, actor, self.collection_factory())
        except N.RunAbort:
            result = {"status": "failed", "codes": ["COLLECTION_DEADLINE"]}
        except Exception:
            result = {"status": "failed", "codes": ["COLLECTION_FAILED"]}
        except BaseException:
            result = {"status": "failed", "codes": ["COLLECTION_INTERRUPTED"]}
            raise
        finally:
            try:
                self.store.record_access(actor, "collection_run", "board", request_id,
                                         result["status"], self.clock())
            except Exception:
                result = {"status": "failed", "codes": ["AUDIT_UNAVAILABLE"]}
            with self._collection_lock:
                self._collection_latest = dict(result, id=request_id)
        if result["status"] in ("failed", "partial"):
            self._errors.append("collection")
        return True

    def _step(self, name, action, *, note=True):
        now = self._monotonic()
        last = self._last.get(name)
        interval = 30 if name == "inventory" else 60
        due = last + interval if last is not None else now
        if name == "inventory":
            due = max(due, self._inventory_ready_at)
        if name in ("accounts", "inventory", "morning"):
            due = max(due, self._naver_rate_ready_at)
        self._next_steps[name] = due
        if now < due:
            return
        self._last[name] = now
        self._next_steps[name] = now + interval
        try:
            result = action()
            if note and result is not None:
                A.note(self.store, self.clock(), result)
        except Exception as exc:
            # 비밀값/업체명/금액이 섞일 수 있는 예외 문자열은 기록하지 않는다.
            log.error("예약 작업 실패: %s %s", name, type(exc).__name__)
            self._errors.append(name)
            source = name if name in A.SOURCE_NAMES else "morning"
            try:
                A.record_system_alert(self.store, self.clock(), source, ["RUNTIME_FAILED"])
            except Exception:
                log.error("예약 작업 실패 기록을 저장하지 못했습니다")

    def next_delay(self):
        """회차 실행 시간을 포함한 다음 예약 대기. 비수집 회차는 60초를 유지한다."""
        if not self.config.inventory_enabled or not self._next_steps:
            return 60.0
        return min(60.0, max(0.0, min(self._next_steps.values()) - self._monotonic()))

    def _hold_naver_rate(self, reader):
        """자동 네이버 단계만 429 휴식을 공유한다. 일반 수집 간격과는 별개다."""
        if getattr(reader, "rate_limited", False) is True:
            self._naver_rate_ready_at = max(self._naver_rate_ready_at, self._monotonic() + N.RATE_PAUSE)
            for name in ("accounts", "inventory", "morning"):
                if name in self._next_steps:
                    self._next_steps[name] = max(self._next_steps[name], self._naver_rate_ready_at)

    def tick(self):
        if not self._lock.acquire(blocking=False):
            return {"state": "busy"}
        try:
            self._errors = []
            self._next_steps = {}
            if self._run_collection():
                # 준비 조회를 다시 반복하지 않는다. 다음 일반 예약 회차는 원래 주기로 판정한다.
                self.last_tick = self.clock()
                self.last_errors = tuple(self._errors)
                return {"state": "failed" if self.last_errors else "ok", "errors": list(self.last_errors)}
            c, st = self.config, self.store
            if c.sync_enabled:
                if Y.org_due(st, self.clock()) or (c.inventory_enabled and self._midnight_source_due(S.SYNC_ORG)):
                    self._step("org", lambda: Y.sync_org(self.erp_factory(), st, self.clock()))
                if Y.stages_due(st, self.clock()) or (c.inventory_enabled and self._midnight_source_due(S.SYNC_STAGES)):
                    self._step("stages", lambda: Y.sync_stages(self.erp_factory(), st, self.clock()))
            if c.links_enabled or c.inventory_enabled:
                if L.accounts_due(st, self.clock()):
                    self._step("accounts", self._accounts)
            if c.links_enabled:
                if L.pairing_due(st, self.clock()):
                    self._step("pairing", lambda: L.pair_links(self.erp_factory(), st, self.clock()))
            if c.inventory_enabled:
                if IC.sync_catalog_due(st, self.clock()) or self._midnight_catalog_due():
                    self._step("inventory_catalog", lambda: IC.sync_catalog(self.erp_factory(), st, self.clock()), note=False)
                self._step("inventory", lambda: self._inventory(), note=False)
                self._step("reports", lambda: st.generate_reports(self.clock()), note=False)
            if c.morning_enabled:
                now = self.clock().astimezone(S.KST)
                if M.CHECK_START <= now.time().replace(tzinfo=None) < M.CHECK_DEADLINE:
                    self._step("readiness", lambda: M.readiness(st, self.clock()))
                if M.morning_due(st, self.clock()):
                    self._step("morning", self._morning)
            # 긴 암호화/전송 때문에 시스템 알림과 아침 심박이 밀리지 않도록 먼저 처리한다.
            if c.alerts_enabled:
                self._step("alerts", lambda: self._alerts(), note=False)
            if c.backup_enabled:
                now = self.clock()
                if any(r["status"] in (S.RUN_DONE, S.RUN_FAILED) for r in st.runs_on(now.astimezone(S.KST).date())):
                    self._step("backup", lambda: self._backup(), note=False)
            if c.metrics_enabled:
                # 공유 성과 재수집/재전송은 아침 심박·백업 뒤에 제한된 회차로 수행한다.
                self._step("metrics", lambda: self._metrics(), note=False)
            self.last_tick = self.clock()
            self.last_errors = tuple(self._errors)
            return {"state": "failed" if self.last_errors else "ok", "errors": list(self.last_errors)}
        finally:
            self._lock.release()

    def _midnight_source_due(self, kind):
        now = self.clock().astimezone(S.KST)
        start = datetime.combine(now.date(), time(0, 1), tzinfo=S.KST)
        if now < start or Y._hold_open(self.store, kind, now):
            return False
        last = self.store.last_sync(kind)
        return last is None or (isinstance(last, dict) and Y._aware(last.get("at")) is not None
                                and Y._aware(last["at"]) < start)

    def _midnight_catalog_due(self):
        now = self.clock().astimezone(S.KST)
        start = datetime.combine(now.date(), time(0, 1), tzinfo=S.KST)
        state = self.store.account_catalog_status()
        if now < start:
            return False
        if state is None:
            return True
        if not isinstance(state, dict):
            return False
        at = Y._aware(state.get("at"))
        return at is None or at < start or at > now

    def _accounts(self):
        reader = self.naver_factory()
        try:
            return L.sync_accounts(reader, self.store, self.clock())
        finally:
            self._hold_naver_rate(reader)

    def _morning(self):
        reader = self.naver_factory()
        try:
            if not self.config.inventory_enabled:
                return M.run_morning(reader, self.store, self.clock, th=self.store.thresholds())
            # 기존 경보/준비검사는 유지하되 상세 점검이 다음 성과 회차를 장시간 막지 않는다.
            with reader.bounded_requests(max_calls=24, max_seconds=30):
                return M.run_morning(reader,
                    _ManagedMorningStore(self.store, self.clock()) if self.config.inventory_enabled else self.store,
                    self.clock, th=self.store.thresholds())
        finally:
            self._hold_naver_rate(reader)

    def _backup(self):
        if self.backup_job is None:
            raise RuntimeError("백업 실행기가 없습니다")
        result = self.backup_job(self.store, self.clock())
        if result.code not in ("WAITING_FOR_MORNING", "RETRY_WAIT", "ALREADY_BACKED_UP", "OFFSITE_OK"):
            self._errors.append("backup")
            A.record_system_alert(self.store, self.clock(), "morning", ["BACKUP_FAILED"])
        return result

    def _inventory(self):
        reader = self.naver_factory()
        # 전일·일요일·수동·보고기간 보충이 한 대기열과 같은 호출 예산을 공유한다.
        started = reader._clock.monotonic()
        before = reader.calls
        try:
            with reader.bounded_requests(max_calls=24, max_seconds=30):
                result = PR.run_performance(reader, self.store, self.clock, max_calls=18, max_seconds=20)
                calls_left = 24-(reader.calls-before)
                seconds_left = 30-(reader._clock.monotonic()-started)
                if calls_left>0 and seconds_left>0 and not reader.rate_limited \
                        and result.code not in ("NOT_READY","SOURCE_CHANGED"):
                    # 실적 단계에서 읽은 계정은 다음 회차에 구조를 읽는다. 계정당 8건·10초도 합산 제한이다.
                    SR.run_structure(reader,self.store,self.clock,max_calls=min(6,calls_left),max_seconds=seconds_left,
                                     exclude_customers=reader.called_customers)
        finally:
            if reader.calls > before:
                # 새 reader의 호출이 이전 회차 후반과 같은 연속 30초 창에 겹치지 않는다.
                self._inventory_ready_at = max(self._inventory_ready_at, self._monotonic() + 30)
                self._next_steps["inventory"] = self._inventory_ready_at
            self._hold_naver_rate(reader)
        # 개별 계정의 실패·재시도는 원장 경고로 남고, 원천 무효만 서비스 실패이다.
        if result.code in ("NOT_READY", "SOURCE_CHANGED"):
            self._errors.append("inventory")
        return result

    def _metrics(self):
        result = G.run_metrics(self.metrics_factory(), self.store, self.clock, self.alert_factory())
        bad_counts = any(result.counts.get(name, 0) for name in ('held', 'retry', 'no_client'))
        if result.code not in ('OUTSIDE_WINDOW', 'RETRY_WAIT', 'DONE') or bad_counts:
            self._errors.append('metrics')
            A.record_system_alert(self.store, self.clock(), 'metrics', ['METRICS_INCOMPLETE'])
        return result

    def _alerts(self):
        poster = self.alert_factory()
        if self.config.morning_enabled:
            return A.run_alerts(self.store, self.clock(), poster, self.policy)
        # 준비 단계에는 아침 점검을 일부러 안 돌린다. 거짓 미점검/정상 심박을 만들지 않는다.
        return A.dispatch(self.store, self.clock(), poster, kind=S.ALERT_SYSTEM)
