"""기존 부를 때 판정들을 한 회차로 연결한다. 네이버 쓰기는 없다."""
from datetime import datetime, timedelta
from copy import deepcopy
import logging
import threading

from naver_engine import alerts as A, links as L, morning as M, store as S, sync as Y, metrics as G, naver_read as N
from naver_runtime import collection_requests as CR

log = logging.getLogger("naver_runtime.scheduler")


class Scheduler:
    def __init__(self, config, store, *, erp_factory=None, naver_factory=None,
                 alert_factory=None, metrics_factory=None, clock=None, backup_job=None,
                 collection_factory=None):
        self.config, self.store = config, store
        self.erp_factory, self.naver_factory = erp_factory, naver_factory
        self.alert_factory, self.backup_job = alert_factory, backup_job
        self.metrics_factory = metrics_factory
        self.collection_factory = collection_factory
        self.clock = clock or (lambda: datetime.now(S.KST))
        self.policy = A.AlertPolicy(config.issue_alerts_from, config.issue_alerts_enabled)
        self._lock = threading.Lock()
        self._last = {}
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
        now = self.clock()
        last = self._last.get(name)
        if last is not None and now < last + timedelta(seconds=60) and now >= last:
            return
        self._last[name] = now
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

    def tick(self):
        if not self._lock.acquire(blocking=False):
            return {"state": "busy"}
        try:
            self._errors = []
            if self._run_collection():
                # 준비 조회를 다시 반복하지 않는다. 다음 일반 예약 회차는 원래 주기로 판정한다.
                self.last_tick = self.clock()
                self.last_errors = tuple(self._errors)
                return {"state": "failed" if self.last_errors else "ok", "errors": list(self.last_errors)}
            c, st = self.config, self.store
            if c.sync_enabled:
                if Y.org_due(st, self.clock()):
                    self._step("org", lambda: Y.sync_org(self.erp_factory(), st, self.clock()))
                if Y.stages_due(st, self.clock()):
                    self._step("stages", lambda: Y.sync_stages(self.erp_factory(), st, self.clock()))
            if c.links_enabled:
                if L.accounts_due(st, self.clock()):
                    self._step("accounts", lambda: L.sync_accounts(self.naver_factory(), st, self.clock()))
                if L.pairing_due(st, self.clock()):
                    self._step("pairing", lambda: L.pair_links(self.erp_factory(), st, self.clock()))
            if c.morning_enabled:
                now = self.clock().astimezone(S.KST)
                if M.CHECK_START <= now.time().replace(tzinfo=None) < M.CHECK_DEADLINE:
                    self._step("readiness", lambda: M.readiness(st, self.clock()))
                if M.morning_due(st, self.clock()):
                    self._step("morning", lambda: M.run_morning(self.naver_factory(), st, self.clock,
                                                                th=st.thresholds()))
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

    def _backup(self):
        if self.backup_job is None:
            raise RuntimeError("백업 실행기가 없습니다")
        result = self.backup_job(self.store, self.clock())
        if result.code not in ("WAITING_FOR_MORNING", "RETRY_WAIT", "ALREADY_BACKED_UP", "OFFSITE_OK"):
            self._errors.append("backup")
            A.record_system_alert(self.store, self.clock(), "morning", ["BACKUP_FAILED"])
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
