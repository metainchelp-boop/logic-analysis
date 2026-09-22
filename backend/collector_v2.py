"""수집 중앙 배정 API (v2) — 코덱스 1.22.0 `collector_v2` 이식판 (2026-09-22 · 자체 개발 2차)

경로(prefix /api/collector/v2)
  POST register · claim · report · release        — 확장(토큰 인증)
  GET  status · readiness                          — 로그인 직원(설정 점검은 관리자)
  POST control                                     — 관리자(전역 정지/재개)
업로드는 **기존 /api/collector/serp** 그대로 쓴다(meta.job 에 임대 계약을 실으면 서버가 작업을 완료 처리).

⚠️ 스위치: 서버 env `COLLECTOR_V2_ENABLED=1`(+선택 `COLLECTOR_V2_POLICY_JSON`). 꺼져 있으면 claim 이 INACTIVE 를 돌려주고
   확장은 **종전 경로(/keywords)로 스스로 폴백**한다 — 코덱스 원안(꺼지면 WAIT_POLICY 로 정지)과 다른 점.
⚠️ 작업 원장은 `sync_daily` 가 유니버스(`collector._keyword_universe`)에서 만든다 — 목표 nvMid 가 없어도(B1).
"""
import logging
import os
import sqlite3
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from auth import get_current_user
import collector_coord as core

router = APIRouter(prefix="/api/collector/v2", tags=["collector-v2"])
logger = logging.getLogger(__name__)


def policy() -> core.Policy:
    return core.policy_from_env()


def requested() -> bool:
    return policy().enabled


def _conn():
    from collector import DB_PATH
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    core.init_db(conn)
    return conn


def _token(value):
    from collector import _auth
    _auth(value)


def _admin(user):
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 수집기 제어 상태를 바꿀 수 있습니다.")


def sync_today(conn, now: Optional[int] = None) -> dict:
    """오늘 작업 원장을 유니버스와 맞춘다(멱등). 실패해도 예외를 밖으로 내지 않는다."""
    try:
        from collector import _keyword_universe, _targets, _slot_of, _effective_date
        uni = _keyword_universe(conn)
        targets = _targets(conn, list(uni.keys()))
        today = _effective_date()
        done = {r[0] for r in conn.execute("SELECT keyword FROM collected_serp WHERE collected_date=?", (today,))}
        return core.sync_daily(conn, today, uni, targets, _slot_of, depth=policy().requested_depth, done_keywords=done)
    except Exception as e:
        logger.warning(f"[collector-v2] 작업 원장 동기화 실패(무시): {e}")
        return {"made": 0, "updated": 0, "error": str(e)[:120]}


_last_sync = {"at": 0}


def _maybe_sync(conn, now: int) -> None:
    """claim 때 10분에 한 번만 원장을 맞춘다(매 claim 마다 유니버스를 돌면 무겁다)."""
    if now - _last_sync["at"] >= 600:
        _last_sync["at"] = now
        sync_today(conn, now)


class Register(BaseModel):
    protocol: int = 2
    workerId: str
    sessionId: str
    version: Optional[str] = ""
    workerNo: Optional[int] = 1
    workerCount: Optional[int] = 1
    state: Optional[str] = "READY"
    reason: Optional[str] = ""
    uploadSummary: Optional[dict] = None   # 📤 4차 — 미전송 보관함 요약


class Claim(BaseModel):
    protocol: int = 2
    workerId: str
    sessionId: str
    hour: Optional[int] = None


class Report(BaseModel):
    protocol: int = 2
    workerId: str
    sessionId: str
    state: str
    reason: Optional[str] = ""
    job: Optional[dict] = None
    uploadSummary: Optional[dict] = None   # 📤 4차


class Control(BaseModel):
    state: str
    reason: Optional[str] = ""


@router.post("/register")
def register(req: Register, x_collector_token: str = Header(None)):
    _token(x_collector_token)
    conn = _conn()
    try:
        now = int(time.time())
        out = core.register(conn, req.workerId, req.sessionId, req.version or "", req.workerNo or 1, req.workerCount or 1,
                            now, policy(), state=req.state or "READY", reason=req.reason or "", upload_summary=req.uploadSummary)
        _maybe_sync(conn, now)
        return out
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        conn.close()


@router.post("/claim")
def claim(req: Claim, x_collector_token: str = Header(None)):
    _token(x_collector_token)
    conn = _conn()
    try:
        now = int(time.time())
        p = policy()
        if not p.enabled:
            return {"protocol": 2, "state": "INACTIVE", "job": None, "serverNow": now}
        _maybe_sync(conn, now)
        try:
            from collector_control import is_paused
            legacy_paused = bool(is_paused(conn, None))
        except Exception:
            legacy_paused = False
        from split_rule import split_ok
        hour = req.hour if req.hour is not None else time.localtime(now).tm_hour
        return core.claim(conn, req.workerId, req.sessionId, now, p, hour, split_ok, legacy_paused=legacy_paused)
    finally:
        conn.close()


@router.post("/report")
def report(req: Report, x_collector_token: str = Header(None)):
    _token(x_collector_token)
    conn = _conn()
    try:
        now = int(time.time())
        out = core.report(conn, req.workerId, req.sessionId, req.state, now, policy(), reason=req.reason or "")
        out["protocol"] = 2
        if req.uploadSummary is not None:
            out["uploadSummaryStatus"] = core.store_upload_summary(conn, req.workerId, req.sessionId, req.uploadSummary, now)
        return out
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        conn.close()


@router.post("/release")
def release(req: Report, x_collector_token: str = Header(None)):
    _token(x_collector_token)
    if not req.job:
        raise HTTPException(status_code=422, detail="job 계약이 없습니다.")
    conn = _conn()
    try:
        now = int(time.time())
        out = core.release(conn, req.job, now, policy(), reason=req.reason or req.state)
        out.update(protocol=2, serverNow=now)
        return out
    finally:
        conn.close()


@router.get("/status")
def status(current_user: dict = Depends(get_current_user)):
    conn = _conn()
    try:
        return core.status(conn, int(time.time()), policy())
    finally:
        conn.close()


@router.get("/readiness")
def readiness(current_user: dict = Depends(get_current_user)):
    _admin(current_user)
    conn = _conn()
    try:
        out = core.readiness(conn, int(time.time()), policy())
        # 4차 — 상품 연결 확인 필요(정확 식별자 없음) 수. 못 재면 None(0 이 아니다).
        try:
            from collector_catalog import unresolved_count
            out["targets"] = {"unresolved": unresolved_count(conn, out.get("day"))}
        except Exception:
            out["targets"] = {"unresolved": None}
        if out["targets"]["unresolved"]:
            out["blockers"] = sorted(set(out.get("blockers", [])) | {"TARGET_IDENTITIES_UNRESOLVED"})
            out["configurationReady"] = False
        return out
    finally:
        conn.close()


@router.get("/daily")
def daily(current_user: dict = Depends(get_current_user)):
    """운영 화면 「어제 결과 · 오늘 진행 · 기계별 보고 · 미전송 · 제어」(5차 · 코덱스 daily 이식판). 읽기 전용."""
    from collector_daily import summary as _daily
    conn = _conn()
    try:
        now = int(time.time())
        try:
            from collector import _keyword_universe, _effective_date
            today = _effective_date()
            universe_total = len(_keyword_universe(conn))
        except Exception:
            import datetime as _dt
            today, universe_total = _dt.date.today().isoformat(), None
        try:
            from collector_catalog import unresolved_count
            unresolved = unresolved_count(conn, today)
        except Exception:
            unresolved = None
        try:
            from collector_heartbeat import machines as _machines
            machines = _machines(conn)
        except Exception:
            machines = None
        try:
            control = core.status(conn, now, policy())["control"]
        except Exception:
            control = None
        try:
            pending = conn.execute("SELECT COUNT(*) FROM collect_requests WHERE status='pending'").fetchone()[0]
        except Exception:
            pending = None
        out = _daily(conn, today, universe_total, unresolved, machines, control, pending, policy().enabled, now)
        out["isAdmin"] = current_user.get("role") in ("admin", "superadmin")
        return out
    finally:
        conn.close()


@router.post("/control")
def control(req: Control, current_user: dict = Depends(get_current_user)):
    _admin(current_user)
    conn = _conn()
    try:
        out = core.set_control(conn, req.state, int(time.time()), reason=req.reason or current_user.get("username", ""))
        out["protocol"] = 2
        logger.warning(f"[collector-v2] 관리자 제어 — {req.state} by {current_user.get('username', '?')}")
        return out
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        conn.close()


def complete_from_upload(meta: Optional[dict], observation_status: str, observation_id: str, stop_reason: str = "") -> Optional[dict]:
    """/serp 가 반영을 끝낸 뒤 부른다. meta.job 이 없으면(구확장·비조정) 아무것도 안 한다. 실패해도 업로드는 성공."""
    job = (meta or {}).get("job") if isinstance(meta, dict) else None
    if not job:
        return None
    try:
        conn = _conn()
        try:
            out = core.complete(conn, job, observation_status, observation_id, int(time.time()), stop_reason=stop_reason)
        finally:
            conn.close()
        if out.get("reason") in ("LEASE_MISMATCH", "NOT_LEASED"):
            logger.warning(f"[collector-v2] 업로드의 임대 계약이 맞지 않음({out.get('reason')}) — 수집분은 종전대로 저장했다")
        return out
    except Exception as e:
        logger.warning(f"[collector-v2] 작업 완료 처리 실패(업로드는 성공): {e}")
        return None
