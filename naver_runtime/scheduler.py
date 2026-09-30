"""기존 부를 때 판정들을 한 회차로 연결한다. 네이버 쓰기는 없다."""
from datetime import datetime, timedelta
import logging
import threading

from naver_engine import alerts as A, links as L, morning as M, store as S, sync as Y, metrics as G

log = logging.getLogger("naver_runtime.scheduler")


class Scheduler:
    def __init__(self, config, store, *, erp_factory=None, naver_factory=None,
                 alert_factory=None, metrics_factory=None, clock=None, backup_job=None):
        self.config, self.store = config, store
        self.erp_factory, self.naver_factory = erp_factory, naver_factory
        self.alert_factory, self.backup_job = alert_factory, backup_job
        self.metrics_factory = metrics_factory
        self.clock = clock or (lambda: datetime.now(S.KST))
        self.policy = A.AlertPolicy(config.issue_alerts_from, config.issue_alerts_enabled)
        self._lock = threading.Lock()
        self._last = {}
        self.last_tick = None
        self.last_errors = ()

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
            A.record_system_alert(self.store, self.clock(), 'morning', ['METRICS_INCOMPLETE'])
        return result

    def _alerts(self):
        poster = self.alert_factory()
        if self.config.morning_enabled:
            return A.run_alerts(self.store, self.clock(), poster, self.policy)
        # 준비 단계에는 아침 점검을 일부러 안 돌린다. 거짓 미점검/정상 심박을 만들지 않는다.
        return A.dispatch(self.store, self.clock(), poster, kind=S.ALERT_SYSTEM)
