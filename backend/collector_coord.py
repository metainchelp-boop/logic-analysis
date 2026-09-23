"""수집 중앙 배정(코디네이터) — 코덱스 1.22.0 `collector_coordinator` 이식판 (2026-09-22 · 자체 개발 2차)

코덱스 원안에서 가져온 것
  · 기계(worker) 등록·세션 · 하루 단위 작업 원장(키워드마다 1건) · **임대(lease)** 로 한 키워드를 한 기계만 맡음 ·
    임대 만료 회수 · 공통/기계별 **시간·일 예산** · 기계별 간격 조절(collector_pacing) · 관리자 제어 상태 · 상태 조회.

코덱스 원안과 **일부러 다르게** 한 것(검토 보고 B1·B2 + 운영 현실)
  · **B1** — 작업은 유니버스 키워드 전부에 만든다(목표 nvMid 가 없어도). 원안은 nvMid 없는 상품·업체를 작업 자체에서 뺐다.
  · **B2** — 깊이는 정책값(기본 300) · 1~1000 어느 값이든 허용. 원안은 300 아니면 정책 무효.
  · **페이지 단위 허가(action permit) 없음** — 원안은 네이버 페이지를 넘길 때마다 서버 허가를 받았다(페이지당 HTTP 1회).
    우리는 **키워드 1건 = 배정 1건** 으로 예산을 센다(키워드당 최대 8장이라 같은 축). 확장이 서버를 못 만나도 회차가 안 죽는다.
  · **전역 정지 없음** — 한 기계가 막히면(캡차) **그 기계만** 6시간 쉰다(원안은 전 기계 정지 + 사람 검토).
    전 기계 정지는 지금도 있는 화면 스위치(collector_control)가 한다.
  · 임대·세션 어긋난 업로드는 **버리지 않는다**(수집분은 종전 경로로 저장 · 작업엔 사유만) — fail-open.

⚠️ stdlib 만. 시각은 서버 epoch 초. 기계 식별 = 확장의 instanceId(무작위 uuid). IP 미저장.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, fields
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

PAUSES = {"PAUSED_OPERATOR", "PAUSED_BLOCK", "PAUSED_AUTH", "PAUSED_UNKNOWN"}
STATES = PAUSES | {"READY", "WAIT_BUDGET"}
BLOCK_REST_SECONDS = 6 * 3600          # 확장의 캡차 쉼(BLOCK_COOLDOWN_MS)과 같은 값 — 그 기계만 쉰다


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    global_hourly: int = 40           # 서버 HOURLY_CAP 과 같은 기본값
    global_daily: int = 1200
    worker_hourly: int = 10           # 시험 상한 10(대표 확정)과 같은 기본값
    worker_daily: int = 240
    min_gap_seconds: int = 40         # 확장 spreadGap 하한과 같은 값
    lease_seconds: int = 600
    session_seconds: int = 900        # 심장박동 5분 × 3
    requested_depth: int = 300
    transient_retries: int = 2
    retry_backoff_seconds: int = 60

    def __post_init__(self):
        for k in ("global_hourly", "global_daily", "worker_hourly", "worker_daily", "transient_retries"):
            if type(getattr(self, k)) is not int or getattr(self, k) < 0:
                raise ValueError("INVALID_POLICY")
        for k in ("min_gap_seconds", "lease_seconds", "session_seconds", "retry_backoff_seconds"):
            if type(getattr(self, k)) is not int or getattr(self, k) <= 0:
                raise ValueError("INVALID_POLICY")
        if type(self.requested_depth) is not int or not 1 <= self.requested_depth <= 1000:
            raise ValueError("INVALID_DEPTH")


def policy_from_env(env: Optional[dict] = None) -> Policy:
    """env COLLECTOR_V2_ENABLED=1 + (선택) COLLECTOR_V2_POLICY_JSON. 정책 JSON 이 깨지면 **꺼진 것**으로 본다(안전)."""
    env = os.environ if env is None else env
    enabled = str(env.get("COLLECTOR_V2_ENABLED", "0")).strip() == "1"
    raw = env.get("COLLECTOR_V2_POLICY_JSON")
    values: Dict[str, Any] = {}
    if raw:
        try:
            got = json.loads(raw)
            names = {f.name for f in fields(Policy)} - {"enabled"}
            if isinstance(got, dict):
                values = {k: v for k, v in got.items() if k in names}
        except (TypeError, ValueError):
            return Policy(enabled=False)
    try:
        return Policy(enabled=enabled, **values)
    except (TypeError, ValueError):
        return Policy(enabled=False)


def policy_to_dict(p: Policy) -> dict:
    return asdict(p)


def business_day(now: float) -> str:
    """서버 로컬(KST) 달력 날짜 — 이 저장소의 다른 날짜 축(collected_date)과 같다."""
    return datetime.fromtimestamp(now).date().isoformat()


def _day_start(now: float) -> int:
    d = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp())


DDL = """
CREATE TABLE IF NOT EXISTS collector_coord_control (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL, updated_at INTEGER NOT NULL);
INSERT OR IGNORE INTO collector_coord_control VALUES(1,'READY','',1,0);
CREATE TABLE IF NOT EXISTS collector_coord_workers (
    worker_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, version TEXT NOT NULL DEFAULT '',
    worker_no INTEGER NOT NULL DEFAULT 1, worker_count INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'READY', reason TEXT NOT NULL DEFAULT '', paused_until INTEGER NOT NULL DEFAULT 0,
    last_seen INTEGER NOT NULL DEFAULT 0, pace_json TEXT NOT NULL DEFAULT '{}', registered_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS collector_coord_jobs (
    job_id TEXT PRIMARY KEY, day TEXT NOT NULL, keyword TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'daily',
    priority INTEGER NOT NULL DEFAULT 1, slot INTEGER NOT NULL DEFAULT 0,
    targets_json TEXT NOT NULL DEFAULT '[]', requested_depth INTEGER NOT NULL DEFAULT 300,
    state TEXT NOT NULL DEFAULT 'pending', lease_id TEXT, worker_id TEXT, session_id TEXT,
    claimed_at INTEGER, lease_expires_at INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
    next_at INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', requested_at INTEGER NOT NULL DEFAULT 0,
    done_at INTEGER, observation_id TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_coord_jobs_daily ON collector_coord_jobs(day, keyword) WHERE kind='daily';
CREATE INDEX IF NOT EXISTS idx_coord_jobs_state ON collector_coord_jobs(day, state);
CREATE TABLE IF NOT EXISTS collector_coord_claims (
    claim_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, worker_id TEXT NOT NULL, claimed_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_coord_claims_time ON collector_coord_claims(claimed_at);
"""


def init_db(conn) -> None:
    conn.executescript(DDL)
    # 📤 4차 — 기계별 미전송 보관함 요약(ALTER 가드 · 멱등)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(collector_coord_workers)").fetchall()}
        for name, ddl in (("upload_summary_json", "TEXT"), ("upload_summary_at", "INTEGER"), ("upload_summary_session", "TEXT")):
            if name not in cols:
                conn.execute(f"ALTER TABLE collector_coord_workers ADD COLUMN {name} {ddl}")
    except Exception:
        pass
    conn.commit()


def normalize_keyword(keyword) -> str:
    """키워드 정규화(코덱스 이식) — NFKC + 공백 정리. 별칭이 억제·매핑을 비켜 가지 못하게 한 곳에서."""
    import unicodedata
    if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 200:
        raise ValueError("INVALID_KEYWORD")
    return " ".join(unicodedata.normalize("NFKC", keyword).split())


def store_upload_summary(conn, worker_id: str, session_id: str, summary, now: int) -> str:
    """register/report 에 실린 보관함 요약을 저장한다. 반환 = 'FRESH' | 'INVALID' | 'NONE'."""
    if summary is None:
        return "NONE"
    try:
        from collector_telemetry import validate_upload_summary
        payload = json.dumps(validate_upload_summary(summary, now=now), ensure_ascii=False)
        status = "FRESH"
    except Exception:
        payload, status = "INVALID", "INVALID"
    try:
        conn.execute("UPDATE collector_coord_workers SET upload_summary_json=?, upload_summary_at=?, upload_summary_session=? WHERE worker_id=?",
                     (payload, now, session_id, worker_id))
        conn.commit()
    except Exception:
        pass
    return status


def _one(conn, sql, args=()):
    cur = conn.execute(sql, args)
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], row))


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _control(conn) -> dict:
    return _one(conn, "SELECT * FROM collector_coord_control WHERE singleton=1") or {"state": "READY", "version": 1, "reason": ""}


# ── 하루 작업 원장 ──────────────────────────────────────────────────────
def sync_daily(conn, day: str, universe: Dict[str, bool], targets: Dict[str, list],
               slot_of: Callable[[str, bool], int], depth: int = 300, done_keywords=()) -> dict:
    """유니버스(키워드 → 우선 여부) 전부에 오늘 작업을 만든다(있으면 목표만 갱신). **B1: 목표가 없어도 만든다.**
    이미 오늘 수집분이 있는 키워드(done_keywords)는 done 으로 둔다. 되돌림: 표만 지우면 된다(수집분 무접촉)."""
    made = updated = 0
    done_set = set(done_keywords or ())
    now = int(datetime.now().timestamp())
    for kw, prio in universe.items():
        k = (kw or "").strip()
        if not k:
            continue
        t = sorted({str(x) for x in (targets.get(k) or []) if str(x).strip()})
        row = _one(conn, "SELECT job_id, state, targets_json FROM collector_coord_jobs WHERE day=? AND keyword=? AND kind='daily'", (day, k))
        if row is None:
            conn.execute("INSERT INTO collector_coord_jobs(job_id, day, keyword, kind, priority, slot, targets_json, requested_depth, state, requested_at, done_at) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (str(uuid4()), day, k, "daily", 1 if prio else 0, int(slot_of(k, bool(prio))), json.dumps(t, ensure_ascii=False),
                          int(depth), "done" if k in done_set else "pending", now, now if k in done_set else None))
            made += 1
        elif row["targets_json"] != json.dumps(t, ensure_ascii=False):
            conn.execute("UPDATE collector_coord_jobs SET targets_json=? WHERE job_id=?", (json.dumps(t, ensure_ascii=False), row["job_id"]))
            updated += 1
        if k in done_set and row is not None and row["state"] in ("pending", "deferred", "held"):
            conn.execute("UPDATE collector_coord_jobs SET state='done', done_at=?, reason='COLLECTED_LEGACY' WHERE job_id=?", (now, row["job_id"]))
    conn.commit()
    return {"made": made, "updated": updated}


# ── 기계 ─────────────────────────────────────────────────────────────
def register(conn, worker_id: str, session_id: str, version: str, worker_no: int, worker_count: int,
             now: int, policy: Policy, state: str = "READY", reason: str = "", upload_summary=None) -> dict:
    wid, sid = str(worker_id or "").strip()[:64], str(session_id or "").strip()[:64]
    if not wid or not sid:
        raise ValueError("INVALID_WORKER")
    if state not in STATES:
        state = "READY"
    old = _one(conn, "SELECT * FROM collector_coord_workers WHERE worker_id=?", (wid,))
    paused_until = int(old["paused_until"]) if old else 0
    # 기계가 스스로 막힘을 알리면 그 기계만 쉰다(6시간) · READY 를 알리면 쉼이 지났을 때만 푼다
    if state == "PAUSED_BLOCK":
        paused_until = max(paused_until, now + BLOCK_REST_SECONDS)
    elif state in PAUSES:
        paused_until = max(paused_until, now + policy.session_seconds)
    eff_state = state
    if paused_until > now and state == "READY":
        eff_state, reason = (old["state"] if old and old["state"] in PAUSES else "PAUSED_BLOCK"), (old["reason"] if old else "REST")
    if old is None:
        conn.execute("INSERT INTO collector_coord_workers(worker_id, session_id, version, worker_no, worker_count, state, reason, paused_until, last_seen, registered_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?)", (wid, sid, str(version or "")[:40], int(worker_no or 1), int(worker_count or 1), eff_state, reason[:120], paused_until, now, now))
    else:
        if old["session_id"] != sid:
            # 새 세션(브라우저 재시작) — 이 기계가 쥐고 있던 임대는 회수한다
            conn.execute("UPDATE collector_coord_jobs SET state='pending', lease_id=NULL, worker_id=NULL, session_id=NULL, reason='SESSION_CHANGED' "
                         "WHERE worker_id=? AND state='leased'", (wid,))
        conn.execute("UPDATE collector_coord_workers SET session_id=?, version=?, worker_no=?, worker_count=?, state=?, reason=?, paused_until=?, last_seen=? WHERE worker_id=?",
                     (sid, str(version or "")[:40], int(worker_no or 1), int(worker_count or 1), eff_state, reason[:120], paused_until, now, wid))
    conn.commit()
    if upload_summary is not None:
        store_upload_summary(conn, wid, sid, upload_summary, now)
    ctl = _control(conn)
    return {"protocol": 2, "workerId": wid, "sessionId": sid, "state": eff_state, "pausedUntil": paused_until,
            "controlState": ctl["state"], "controlVersion": ctl["version"], "serverNow": now,
            "enabled": policy.enabled, "policy": policy_to_dict(policy)}


def _expire_leases(conn, now: int) -> int:
    cur = conn.execute("UPDATE collector_coord_jobs SET state='pending', lease_id=NULL, worker_id=NULL, session_id=NULL, reason='LEASE_EXPIRED' "
                       "WHERE state='leased' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?", (now,))
    return cur.rowcount or 0


def _budget_wait(conn, worker_id: str, now: int, policy: Policy) -> Optional[int]:
    """예산·간격을 넘겼으면 다음 허용 시각(epoch), 아니면 None."""
    day0 = _day_start(now)
    since = min(day0, now - 3600)
    claims = _rows(conn, "SELECT worker_id, claimed_at FROM collector_coord_claims WHERE claimed_at >= ?", (since,))
    waits: List[int] = []
    for scope, hourly, daily in ((None, policy.global_hourly, policy.global_daily), (worker_id, policy.worker_hourly, policy.worker_daily)):
        scoped = sorted(c["claimed_at"] for c in claims if scope is None or c["worker_id"] == scope)
        recent = [t for t in scoped if t > now - 3600]
        if hourly and len(recent) >= hourly:
            waits.append(recent[-hourly] + 3600)
        if daily and sum(1 for t in scoped if t >= day0) >= daily:
            waits.append(day0 + 86400)
    # 기계별 간격(pace) — 마지막 배정 + interval
    w = _one(conn, "SELECT pace_json FROM collector_coord_workers WHERE worker_id=?", (worker_id,))
    interval = policy.min_gap_seconds
    try:
        pace = json.loads((w or {}).get("pace_json") or "{}")
        iv = pace.get("intervalSeconds")
        if isinstance(iv, (int, float)) and iv > 0:
            interval = max(policy.min_gap_seconds, min(float(iv), policy.min_gap_seconds * 4))
    except Exception:
        pass
    mine = [c["claimed_at"] for c in claims if c["worker_id"] == worker_id]
    if mine:
        waits.append(int(max(mine) + interval))
    wait = max(waits) if waits else 0
    return wait if wait > now else None


def claim(conn, worker_id: str, session_id: str, now: int, policy: Policy, hour: int,
          split_ok: Callable[[str, int, int], bool], legacy_paused: bool = False) -> dict:
    """이 기계가 지금 할 키워드 1건을 임대한다. 순서 = /keywords 와 같은 규칙(이번 시간대 슬롯 → 밀린 슬롯 · 시도한 것은 뒤로)."""
    if not policy.enabled:
        return {"protocol": 2, "state": "INACTIVE", "job": None, "serverNow": now}
    _expire_leases(conn, now)
    w = _one(conn, "SELECT * FROM collector_coord_workers WHERE worker_id=?", (worker_id,))
    if w is None or w["session_id"] != session_id:
        return {"protocol": 2, "state": "SESSION_MISMATCH", "job": None, "serverNow": now}
    conn.execute("UPDATE collector_coord_workers SET last_seen=? WHERE worker_id=?", (now, worker_id))
    ctl = _control(conn)
    if legacy_paused or ctl["state"] != "READY":
        conn.commit()
        return {"protocol": 2, "state": "PAUSED_OPERATOR", "reason": ctl.get("reason") or "화면 스위치 꺼짐", "job": None, "serverNow": now}
    if int(w["paused_until"] or 0) > now:
        conn.commit()
        return {"protocol": 2, "state": w["state"] if w["state"] in PAUSES else "PAUSED_BLOCK", "reason": w["reason"],
                "pausedUntil": int(w["paused_until"]), "job": None, "serverNow": now}
    if w["state"] in PAUSES:   # 쉼이 지났다 — 자동 복귀(사람 검토 없음)
        conn.execute("UPDATE collector_coord_workers SET state='READY', reason='' WHERE worker_id=?", (worker_id,))
    existing = _one(conn, "SELECT * FROM collector_coord_jobs WHERE worker_id=? AND session_id=? AND state='leased'", (worker_id, session_id))
    if existing:
        conn.commit()
        return {"protocol": 2, "state": "LEASED", "job": _wire(existing, ctl["version"]), "serverNow": now}
    wait = _budget_wait(conn, worker_id, now, policy)
    if wait:
        conn.commit()
        return {"protocol": 2, "state": "WAIT_BUDGET", "nextAllowedAt": wait, "job": None, "serverNow": now}
    day = business_day(now)
    wno, wcnt = int(w["worker_no"] or 1), int(w["worker_count"] or 1)
    cands = _rows(conn, "SELECT * FROM collector_coord_jobs WHERE day=? AND state IN ('pending','deferred') AND next_at <= ? "
                        "ORDER BY (kind='realtime') DESC, requested_at", (day, now))
    h = max(0, min(23, int(hour)))
    # 대표 결정 B(2026-09-23) — /keywords 와 같은 규칙: 시도 횟수 다음으로 **오래 안 모은 키워드부터**.
    try:
        from collect_order import last_collected_map
        last = last_collected_map(conn)
    except Exception:
        last = {}
    now_slot, overdue, later = [], [], []
    for j in cands:
        if wcnt > 1 and not split_ok(j["keyword"], wno - 1, wcnt):
            continue
        s = int(j["slot"] or 0)
        key = (j["attempts"], last.get(j["keyword"], "") or "", s, j["keyword"])
        if j["kind"] == "realtime" or s == h:
            now_slot.append((key, j))
        elif s < h:
            overdue.append((key, j))
        else:
            later.append((key, j))
    now_slot.sort(key=lambda x: x[0]); overdue.sort(key=lambda x: x[0]); later.sort(key=lambda x: x[0])
    pick = (now_slot or overdue or later)
    if not pick:
        conn.commit()
        return {"protocol": 2, "state": "IDLE", "job": None, "serverNow": now}
    job = pick[0][1]
    lease = str(uuid4())
    conn.execute("UPDATE collector_coord_jobs SET state='leased', lease_id=?, worker_id=?, session_id=?, claimed_at=?, lease_expires_at=?, attempts=attempts+1, reason='' WHERE job_id=?",
                 (lease, worker_id, session_id, now, now + policy.lease_seconds, job["job_id"]))
    conn.execute("INSERT INTO collector_coord_claims(claim_id, job_id, worker_id, claimed_at) VALUES(?,?,?,?)", (str(uuid4()), job["job_id"], worker_id, now))
    conn.commit()
    job = _one(conn, "SELECT * FROM collector_coord_jobs WHERE job_id=?", (job["job_id"],))
    return {"protocol": 2, "state": "LEASED", "job": _wire(job, ctl["version"]), "serverNow": now}


def _wire(job: dict, control_version: Optional[int] = None) -> dict:
    out = {"protocol": 2, "jobId": job["job_id"], "leaseId": job["lease_id"], "workerId": job["worker_id"], "sessionId": job["session_id"],
           "day": job["day"], "keyword": job["keyword"], "kind": job["kind"], "targetIds": json.loads(job["targets_json"] or "[]"),
           "requestedDepth": int(job["requested_depth"] or 300), "leaseExpiresAt": job["lease_expires_at"], "claimedAt": job["claimed_at"]}
    if control_version is not None:
        out["controlVersion"] = control_version
    return out


def owned(conn, contract: Any) -> Optional[dict]:
    """업로드/해제에 실린 job 계약이 지금 임대와 맞는가. 안 맞으면 None(호출자는 fail-open)."""
    if not isinstance(contract, dict) or contract.get("protocol") != 2:
        return None
    job = _one(conn, "SELECT * FROM collector_coord_jobs WHERE job_id=?", (contract.get("jobId"),))
    if not job:
        return None
    if any(contract.get(k) != v for k, v in (("leaseId", job["lease_id"]), ("workerId", job["worker_id"]), ("sessionId", job["session_id"]))):
        return None
    return job


def complete(conn, contract: Any, observation_status: str, observation_id: str, now: int, stop_reason: str = "") -> dict:
    """업로드가 반영된 뒤 작업 상태를 정한다. complete/target_complete → done · partial → deferred(오늘 다시) · failed → held."""
    job = owned(conn, contract)
    if not job:
        return {"job": None, "reason": "LEASE_MISMATCH"}
    if job["state"] != "leased":
        return {"job": job["job_id"], "reason": "NOT_LEASED", "state": job["state"]}
    if observation_status in ("complete", "target_complete", "legacy"):
        state, reason = "done", ""
    elif observation_status == "partial":
        state, reason = "deferred", (stop_reason or "PARTIAL")[:60]
    else:
        state, reason = "held", (stop_reason or observation_status or "FAILED")[:60]
    conn.execute("UPDATE collector_coord_jobs SET state=?, reason=?, done_at=?, observation_id=?, lease_id=NULL, next_at=? WHERE job_id=?",
                 (state, reason, now if state == "done" else None, observation_id, now + 600 if state == "deferred" else 0, job["job_id"]))
    # 기계 간격 조절 — 성공이면 사이클 시간 표본, 실패면 벌점
    try:
        from collector_pacing import update as _pace
        w = _one(conn, "SELECT pace_json FROM collector_coord_workers WHERE worker_id=?", (job["worker_id"],))
        prev = json.loads((w or {}).get("pace_json") or "{}") or None
        if state == "done":
            dur = max(1, now - int(job["claimed_at"] or now))
            st = _pace(prev, duration_seconds=float(dur), action_count=1, outcome="success", base_interval=float(_base_gap()))
        else:
            st = _pace(prev, outcome="transient_error", base_interval=float(_base_gap()))
        conn.execute("UPDATE collector_coord_workers SET pace_json=? WHERE worker_id=?", (json.dumps(st), job["worker_id"]))
    except Exception:
        pass
    conn.commit()
    return {"job": job["job_id"], "state": state, "reason": reason}


_BASE_GAP = 40


def _base_gap() -> int:
    return _BASE_GAP


def release(conn, contract: Any, now: int, policy: Policy, reason: str = "") -> dict:
    """확장이 손대지 않고 돌려주는 임대(예산 대기·사람이 멈춤 등). 재시도 횟수 초과면 held."""
    job = owned(conn, contract)
    if not job or job["state"] != "leased":
        return {"state": "LEASE_MISMATCH"}
    retry = job["attempts"] <= policy.transient_retries
    next_at = now + policy.retry_backoff_seconds * (2 ** max(0, job["attempts"] - 1)) if retry else 0
    conn.execute("UPDATE collector_coord_jobs SET state=?, lease_id=NULL, worker_id=NULL, session_id=NULL, next_at=?, reason=? WHERE job_id=?",
                 ("pending" if retry else "held", next_at, (reason or "RELEASED")[:60], job["job_id"]))
    conn.commit()
    return {"state": "WAIT_BUDGET" if retry else "HELD", "nextAllowedAt": next_at}


def report(conn, worker_id: str, session_id: str, state: str, now: int, policy: Policy, reason: str = "") -> dict:
    """기계가 자기 상태를 알린다(막힘·재개). 막힘은 **그 기계만** 쉰다."""
    if state not in STATES:
        raise ValueError("INVALID_STATE")
    w = _one(conn, "SELECT * FROM collector_coord_workers WHERE worker_id=?", (worker_id,))
    if not w or w["session_id"] != session_id:
        return {"state": "SESSION_MISMATCH"}
    paused_until = int(w["paused_until"] or 0)
    if state == "PAUSED_BLOCK":
        paused_until = max(paused_until, now + BLOCK_REST_SECONDS)
        conn.execute("UPDATE collector_coord_jobs SET state='pending', lease_id=NULL, worker_id=NULL, session_id=NULL, reason='WORKER_BLOCKED' "
                     "WHERE worker_id=? AND state='leased'", (worker_id,))
    elif state in PAUSES:
        paused_until = max(paused_until, now + policy.session_seconds)
    elif state == "READY":
        paused_until = 0 if paused_until <= now else paused_until   # 쉼이 아직이면 READY 로 못 돌린다
    eff = state if (state not in ("READY",) or paused_until <= now) else w["state"]
    conn.execute("UPDATE collector_coord_workers SET state=?, reason=?, paused_until=?, last_seen=? WHERE worker_id=?",
                 (eff if eff in STATES else "READY", (reason or "")[:120], paused_until, now, worker_id))
    conn.commit()
    return {"state": eff, "pausedUntil": paused_until, "serverNow": now}


def set_control(conn, state: str, now: int, reason: str = "") -> dict:
    if state not in PAUSES | {"READY"}:
        raise ValueError("INVALID_STATE")
    conn.execute("UPDATE collector_coord_control SET state=?, reason=?, version=version+1, updated_at=? WHERE singleton=1", (state, (reason or "")[:120], now))
    if state != "READY":
        conn.execute("UPDATE collector_coord_jobs SET state='pending', lease_id=NULL, worker_id=NULL, session_id=NULL, reason='CONTROL_PAUSED' WHERE state='leased'")
    conn.commit()
    return {"state": state, "controlVersion": _control(conn)["version"]}


def status(conn, now: int, policy: Policy) -> dict:
    day = business_day(now)
    _expire_leases(conn, now)
    jobs = _rows(conn, "SELECT state, COUNT(*) n FROM collector_coord_jobs WHERE day=? GROUP BY state", (day,))
    counts = {r["state"]: r["n"] for r in jobs}
    workers = []
    for w in _rows(conn, "SELECT * FROM collector_coord_workers ORDER BY worker_no, last_seen DESC"):
        online = int(w["last_seen"] or 0) + policy.session_seconds > now
        st = w["state"]
        if int(w["paused_until"] or 0) > now and st not in PAUSES:
            st = "PAUSED_BLOCK"
        try:
            from collector_telemetry import reported_upload_summary
            us, us_status = reported_upload_summary(w.get("upload_summary_json"), w.get("upload_summary_at"), now=now,
                                                    session_id=w["session_id"], summary_session=w.get("upload_summary_session"))
        except Exception:
            us, us_status = None, "INVALID"
        workers.append({"workerId": w["worker_id"], "machine": f"{w['worker_no']}/{w['worker_count']}", "version": w["version"],
                        "state": st if online else "OFFLINE", "reason": w["reason"], "lastSeen": w["last_seen"], "online": online,
                        "pausedUntil": int(w["paused_until"] or 0), "pace": json.loads(w["pace_json"] or "{}"),
                        "uploadSummary": us, "uploadSummaryStatus": us_status})
    day0 = _day_start(now)
    claims_today = _one(conn, "SELECT COUNT(*) n FROM collector_coord_claims WHERE claimed_at >= ?", (day0,))["n"]
    claims_hour = _one(conn, "SELECT COUNT(*) n FROM collector_coord_claims WHERE claimed_at > ?", (now - 3600,))["n"]
    ctl = _control(conn)
    conn.commit()
    return {"protocol": 2, "enabled": policy.enabled, "day": day, "serverNow": now, "control": ctl,
            "jobs": {"total": sum(counts.values()), **{k: counts.get(k, 0) for k in ("pending", "leased", "deferred", "held", "done")}},
            "claims": {"today": claims_today, "lastHour": claims_hour,
                       "globalHourly": policy.global_hourly, "globalDaily": policy.global_daily,
                       "workerHourly": policy.worker_hourly, "workerDaily": policy.worker_daily},
            "workers": workers, "policy": policy_to_dict(policy)}


def readiness(conn, now: int, policy: Policy, env: Optional[dict] = None) -> dict:
    """설정 점검(코덱스 readiness 이식판) — 켜기 전에 무엇이 막는지 한 장으로. 읽기 전용."""
    env = os.environ if env is None else env
    blockers: List[str] = []
    raw_enabled = str(env.get("COLLECTOR_V2_ENABLED", "0")).strip()
    if raw_enabled not in ("0", "1", ""):
        blockers.append("V2_ENABLED_INVALID")
    if not policy.enabled:
        blockers.append("V2_DISABLED")
    raw = env.get("COLLECTOR_V2_POLICY_JSON")
    if raw:
        try:
            json.loads(raw)
        except Exception:
            blockers.append("V2_POLICY_INVALID")
    st = status(conn, now, policy)
    ready_workers = [w for w in st["workers"] if w["online"] and w["state"] == "READY"]
    if not ready_workers:
        blockers.append("NO_READY_ONLINE_WORKER")
    if st["control"]["state"] != "READY":
        blockers.append("COLLECTION_PAUSED")
    if st["jobs"]["total"] == 0:
        blockers.append("NO_JOBS_TODAY(sync_daily 전)")
    remaining = st["jobs"]["pending"] + st["jobs"]["deferred"] + st["jobs"]["leased"]
    hours_left = max(0.0, (_day_start(now) + 86400 - now) / 3600.0)
    ceiling = int(min(policy.global_hourly * hours_left, len(ready_workers) * policy.worker_hourly * hours_left,
                      max(0, policy.global_daily - st["claims"]["today"])))
    if remaining > ceiling:
        blockers.append("REMAINING_EXCEEDS_TODAY_BUDGET")
    return {"protocol": 2, "serverNow": now, "day": st["day"], "configurationReady": not blockers, "blockers": sorted(set(blockers)),
            "policy": policy_to_dict(policy), "workers": {"total": len(st["workers"]), "ready": len(ready_workers),
                                                         "online": sum(1 for w in st["workers"] if w["online"])},
            "jobs": st["jobs"], "claims": st["claims"], "capacity": {"remainingJobs": remaining, "todayCeiling": ceiling, "hoursLeft": round(hours_left, 2)},
            "control": st["control"]}


def purge_old(conn, days: int = 14) -> int:
    try:
        d = (datetime.now() - timedelta(days=days)).date().isoformat()
        n = conn.execute("DELETE FROM collector_coord_jobs WHERE day < ?", (d,)).rowcount or 0
        conn.execute("DELETE FROM collector_coord_claims WHERE claimed_at < ?", (int(datetime.now().timestamp()) - days * 86400,))
        conn.commit()
        return n
    except Exception:
        return -1
