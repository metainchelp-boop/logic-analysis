"""실행 스레드의 실제 진척만 관찰한다. 조회는 원천·DB·네트워크를 읽지 않는다."""
from datetime import timedelta
import math
import threading


PROGRESS_SECONDS = 45
SOURCE_STEPS = frozenset({"org", "stages", "accounts", "pairing", "inventory_catalog"})


class RuntimeStatus:
    def __init__(self, *, enabled, clock, monotonic, stopped=lambda: False):
        self.enabled = enabled
        self._clock, self._monotonic, self._stopped = clock, monotonic, stopped
        self._lock = threading.Lock()
        self._owner = None
        self._state, self._reason = "starting", "STARTING"
        self._verified_at = None
        self._observed = self._expires = 0.0
        self._blocks = {}
        self._rate_until, self._rate_at = 0.0, None

    def _signal(self, seconds=PROGRESS_SECONDS):
        # 호출자는 잠금을 짧게 보유한다. 외부 작업 중에는 이 잠금을 보유하지 않는다.
        now = self._monotonic()
        self._verified_at = self._clock().isoformat()
        self._observed, self._expires = now, now + seconds

    def begin_cycle(self):
        with self._lock:
            self._owner = threading.get_ident()
            self._state, self._reason = "waiting", "WAITING"
            self._signal()

    def begin_step(self, name):
        with self._lock:
            if name in SOURCE_STEPS:
                self._state, self._reason = "source_sync", "SOURCE_SYNC"
            elif name in ("inventory", "morning", "collection"):
                self._state, self._reason = "collecting", "COLLECTING"
            else:
                self._state, self._reason = "waiting", "BACKUP_RUNNING" if name == "backup" else "WAITING"
            self._signal()

    def finish_step(self, name, problem=None):
        with self._lock:
            if problem is None:
                self._blocks.pop(name, None)
            else:
                self._blocks[name] = problem
            self._state, self._reason = "waiting", "WAITING"
            self._signal()

    def finish_cycle(self, delay, *, idle=False, verified=False):
        with self._lock:
            if verified:
                self._blocks.pop("scheduler", None)
                # 실제 수집 검증은 과거 실행 실패 신호만 복구한다. 원천별 차단·감사는 별개다.
                self._blocks.pop("collection", None)
            self._state, self._reason = ("idle", "IDLE") if idle else ("waiting", "WAITING")
            self._signal(max(0.0, min(60.0, delay)) + 10)
            self._owner = None

    def fail_cycle(self):
        with self._lock:
            self._blocks["scheduler"] = ("error", "RUNTIME_ERROR")
            self._signal()
            self._owner = None

    def rate_pause(self, until):
        with self._lock:
            if until > self._rate_until:
                self._rate_until = until
                self._rate_at = (self._clock() + timedelta(seconds=max(0, until-self._monotonic()))).isoformat()

    def network_started(self, timeout):
        with self._lock:
            if self._owner == threading.get_ident():
                self._signal(max(0.0, min(30.0, timeout)) + 5)

    def network_finished(self, service, status):
        with self._lock:
            if self._owner != threading.get_ident():
                return
            self._signal()
            if service == "naver" and status == 429:
                # 표시만 관찰한다. 실제 중지·재시도와 회차 후 대기는 reader/scheduler 소유다.
                from naver_engine.naver_read import RATE_PAUSE
                until = self._monotonic() + RATE_PAUSE
                if until > self._rate_until:
                    self._rate_until = until
                    self._rate_at = (self._clock() + timedelta(seconds=RATE_PAUSE)).isoformat()

    def sleeping(self, seconds):
        with self._lock:
            if self._owner == threading.get_ident():
                self._signal(max(0.0, min(600.0, seconds)) + 5)
                # 코드 1016도 429와 같은 reader 휴식을 만든다. 본문을 다시 해석하지 않는다.
                from naver_engine.naver_read import RATE_PAUSE
                if seconds == RATE_PAUSE:
                    self._rate_until = max(self._rate_until, self._monotonic() + seconds)
                    self._rate_at = (self._clock() + timedelta(seconds=self._rate_until-self._monotonic())).isoformat()

    def snapshot(self):
        now, stopped = self._monotonic(), self._stopped()
        with self._lock:
            valid = max(0.0, self._expires-now) if math.isfinite(now) else 0.0
            state, reason = self._state, self._reason
            retry_at = None
            if stopped:
                state, reason = "stopped", "STOPPED"
            elif not self.enabled:
                state, reason = "disabled", "DISABLED"
            elif self._verified_at is None:
                state, reason = "starting", "STARTING"
            elif not math.isfinite(now) or now < self._observed or now >= self._expires:
                state, reason, valid = "stale", "STALE", 0.0
            elif self._blocks:
                # 고정 코드만 저장한다. 다음 빈 회차는 실패한 원천/작업의 성공을 대신하지 않는다.
                state, reason = next((p for p in self._blocks.values() if p[0] == "error"),
                                     next(iter(self._blocks.values())))
            elif now < self._rate_until:
                state, reason, retry_at = "rate_paused", "RATE_LIMITED", self._rate_at
            return {"state": state,
                    "indicator": "green" if state in ("source_sync", "collecting", "waiting", "idle") else "red",
                    "reason_code": reason, "verified_at": self._verified_at,
                    "valid_for_seconds": min(3600.0, valid), "retry_at": retry_at}
