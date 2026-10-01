"""대표의 즉시 읽기 요청. 기존 저장소·읽기 규칙만 사용하며 시작 작업을 재생하지 않는다."""
from datetime import datetime, time, timedelta

from naver_engine import morning as M, naver_read as N, store as S, sync as Y, links as L
from naver_engine.sync import is_current_owner as owner_allowed

COUNT_KEYS = frozenset({"targets", "ok", "partial", "key_rejected", "data_late", "system_gap", "link_broken",
                        "link_missing", "not_eligible", "deadline_left", "abort_left", "account_error",
                        "handle_invalid", "store_refused", "duplicate_skipped", "unlinked_issues"})
OUTCOME_CODES = frozenset(value for name, value in vars(M).items() if name.startswith("CODE_")) | {"RETRY_NOT_DUE"}


class CollectionClock:
    """실제 시각을 보존하고 준비·수집 전체의 송신/대기/timeout을 최대 600초로 묶는다."""
    def __init__(self, base, seconds=600):
        if type(seconds) is not int or not 1 <= seconds <= 600:
            raise ValueError("요청 시간은 1~600초여야 합니다")
        self.base, self.seconds = base, seconds
        now = base.now()
        tomorrow = now.astimezone(S.KST).date() + timedelta(days=1)
        self.deadline = min(now + timedelta(seconds=seconds), datetime.combine(tomorrow, time.min, tzinfo=S.KST))
        self.end = base.monotonic() + (self.deadline - now).total_seconds()

    def remaining(self):
        if hasattr(self.base, "before_network"):
            self.base.before_network()
        left = min(self.end - self.base.monotonic(), (self.deadline - self.base.now()).total_seconds())
        if left <= 0:
            raise N.RunAbort("collection-time-budget")
        return left

    def before_network(self):
        self.remaining()

    def now(self):
        return self.base.now()  # 마감 이후에도 회차 정리에는 실제 시각이 필요하다.

    def epoch_ms(self):
        self.remaining()
        return self.base.epoch_ms()

    def monotonic(self):
        self.remaining()
        return self.base.monotonic()

    def sleep(self, seconds):
        self.base.sleep(min(seconds, self.remaining()))
        self.remaining()


def restricted(config):
    return (config.sync_enabled and config.links_enabled and config.morning_enabled
            and config.web_enabled and not config.alerts_enabled and not config.metrics_enabled
            and not config.issue_alerts_enabled)


def refused(code):
    return {"id": None, "status": "refused", "codes": [code]}


def request_limit(store, now, *, exclude_id=None):
    """준비 조회도 전사 공통 제한에 포함한다. 읽은 감사 범위가 하루를 덮지 못하면 닫는다."""
    rows = store.access_log(limit=S.ACCESS_LOG_MAX_READ)
    today = now.astimezone(S.KST).date()
    if len(rows) == S.ACCESS_LOG_MAX_READ and datetime.fromisoformat(rows[-1]["at"]).astimezone(S.KST).date() >= today:
        return "AUDIT_WINDOW_FULL"
    accepted = [datetime.fromisoformat(r["at"]) for r in rows
                if r["action"] == "collection_request" and r["result"] == "accepted" and r["log_id"] != exclude_id]
    if sum(at.astimezone(S.KST).date() == today for at in accepted) >= M.MAX_RUNS_PER_DAY:
        return M.CODE_RUNS_EXHAUSTED
    runs = store.runs_on(today)
    if len(runs) >= M.MAX_RUNS_PER_DAY:
        return M.CODE_RUNS_EXHAUSTED
    if any(r["status"] == S.RUN_RUNNING for r in runs):
        return M.CODE_RUN_RUNNING
    ends = [datetime.fromisoformat(r["finished_at"]) for r in runs if r["finished_at"]]
    if any(now - at < M.RETRY_AFTER for at in accepted + ends):
        return "RETRY_NOT_DUE"
    return None


def recovered_status(store):
    """감사는 상태 표시에만 쓴다. 재시작 시 메모리 큐를 절대로 되살리지 않는다."""
    rows = store.access_log(limit=S.ACCESS_LOG_MAX_READ)
    request = next((r for r in rows if r["action"] == "collection_request" and r["result"] == "accepted"), None)
    if request is None:
        return {"id": None, "status": "idle", "codes": []}
    last = next((r for r in rows if r["action"] == "collection_run" and r["target_id"] == request["log_id"]), None)
    if last is not None and last["result"] in {"done", "partial", "refused", "failed"}:
        return {"id": request["log_id"], "status": last["result"], "codes": ["STATUS_FROM_AUDIT"]}
    return {"id": request["log_id"], "status": "failed", "codes": ["PROCESS_RESTARTED_NOT_REPLAYED"]}


def collect(store, actor, options):
    clock = options["clock"]
    if not isinstance(clock, CollectionClock):
        return refused("COLLECTION_UNAVAILABLE")
    for kind in (S.SYNC_ORG, S.SYNC_STAGES, S.SYNC_ACCOUNTS):
        hold = store.hold(kind)
        if (hold is not None and hold["used_at"] is None
                and clock.now() - hold["at"] <= S.HOLD_TTL):
            return refused("HOLD_PENDING")
    clock.remaining()
    org = Y.sync_org(options["erp_factory"](), store, clock.now())
    if org.outcome != S.SYNC_ACCEPTED:
        return refused("ORG_NOT_ACCEPTED")
    if not owner_allowed(store, actor, clock.now()):
        return refused("OWNER_REQUIRED")
    clock.remaining()
    stages = Y.sync_stages(options["erp_factory"](), store, clock.now())
    if stages.outcome != S.SYNC_ACCEPTED:
        return refused("STAGES_NOT_ACCEPTED")
    clock.remaining()
    accounts = L.sync_accounts(options["naver_factory"](), store, clock.now())
    if accounts.outcome != S.SYNC_ACCEPTED:
        return refused("ACCOUNTS_NOT_ACCEPTED")
    clock.remaining()
    paired = L.pair_links(options["erp_factory"](), store, clock.now())
    if paired.outcome != S.SYNC_ACCEPTED:
        return refused("PAIRING_NOT_ACCEPTED")
    clock.remaining()
    result = M.run_requested(options["naver_factory"](), store, clock.now,
                             max_seconds=clock.seconds, deadline=clock.deadline, th=store.thresholds())
    counts = {key: value for key, value in result.counts.items()
              if key in COUNT_KEYS and type(value) is int and value >= 0}
    codes = [code for code in result.codes if code in OUTCOME_CODES]
    partial = (counts.get("targets", 0) != counts.get("ok", 0) or any(
        value for key, value in counts.items() if key not in {"targets", "ok", "unlinked_issues"}))
    status = "partial" if result.outcome == M.OUT_DONE and partial else result.outcome
    return {"status": status, "codes": codes, "run_id": result.run_id, "counts": counts}
