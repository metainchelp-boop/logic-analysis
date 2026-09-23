"""수집기 서버 설정 — 교체 없이 서버 배포만으로 수집기를 조절한다 (v1.27.0 · 대표 확정 2026-09-23)

대표 지시 「서버 배포만으로도 편리하게 할 수 있게 하면 되잖아」 → 시안 v1 → 「추천대로 확정해」.
확정 5건:
  ① 설정을 바꾸는 손 = **이 파일을 고치고 배포**(기록·시험이 남는다 · 관리자 화면은 다음 차수)
  ② 반영 속도 = **5분 안** — 살아있음 신호(heartbeat) 응답과 매시 작업 목록 응답에 함께 싣는다
  ③ **기계별 다른 값 허용** — WORKER_OVERRIDES
  ④ 캡차 6시간 쉼을 서버에서 푸는 길은 **만들지 않는다**(명령 목록에 없다 · 안전선이 1시간 밑을 막는다)
  ⑤ 기계 번호는 **서버가 배정** — ASSIGNMENTS(비어 있으면 팝업 값 그대로 = 지금과 같다)

어떻게 바꾸나
  · 두 대 모두 같이 → SETTINGS 의 값을 고친다.
  · 한 대만 → WORKER_OVERRIDES[기계 번호] 에 그 칸만 적는다. 예: {2: {"pageGapMinMs": 2000, "pageGapMaxMs": 5000}}
  · 이 기계만 멈춤 → WORKER_OVERRIDES[번호] = {"machinePaused": True}
  · 한 번만 시키기 → COMMANDS 에 {"id": 겹치지 않는 이름, "kind": ..., "until": 만료 시각, "worker": 번호|None}
  · 고친 뒤 SETTINGS_REV 를 1 올린다(시험이 기본값 지문과 REV 를 함께 고정해 둬서, 값만 바꾸고 REV 를 안
    올리면 게이트가 막는다 — 화면에서 「몇 번 설정이 들어갔나」를 사람이 읽을 수 있게 하려는 것).

⚠️ 안전선(넘을 수 없는 범위)은 **수집기 안**(`collector-extension/remote_settings.js` FENCES)에 박혀 있다.
   여기서 선 밖의 값을 보내도 수집기가 선으로 당겨 쓴다. 서버도 같은 선으로 미리 잘라 보내서
   「서버가 보낸 값 = 수집기가 쓴 값」이 되게 한다(설정 지문이 양쪽에서 같게 나온다).
⚠️ 이 파일의 DEFAULTS·FENCES 는 remote_settings.js 와 **같아야** 한다 — 시험(test_collector_settings.py)이
   node 로 그 파일을 실행해 한 칸씩 대조한다.
⚠️ stdlib 만 쓴다(배포 게이트에 fastapi 가 없다).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

# ── 설정 번호 — 값을 바꾸면 1 올린다 ────────────────────────────────────────────
SETTINGS_REV = 1
# 번호별 설정 지문 장부 — SETTINGS·WORKER_OVERRIDES 를 고치면 REV 를 올리고 여기에 한 줄 더한다.
#   지문은 `python -c "import collector_settings as c; print(c.config_fingerprint())"` 로 뽑는다.
#   ⚠️ 시험(test_collector_settings.py)이 「지금 REV 의 지문 = 장부의 지문」을 확인한다 —
#      값만 바꾸고 번호를 안 올리면 게이트가 막는다(화면의 「n번 적용됨」이 거짓말이 되지 않게).
REV_LEDGER = {
    1: "d2176d65",   # 2026-09-23 첫 판 — 전부 기본값(v1.26.0 과 동일)
}

MIN = 60 * 1000
HOUR = 60 * MIN

# ── 기본값 = 수집기 v1.26.0 에 박혀 있던 값(= remote_settings.js DEFAULTS) ──────────
DEFAULTS: Dict[str, Any] = {
    "spreadMinMs": 40000, "spreadLo": 0.4, "spreadHi": 1.8,
    "pageGapMinMs": 1200, "pageGapMaxMs": 3000,
    "hourBudgetMs": 3000000, "hourTailMs": 300000,
    "onDemandGapMs": 20000, "onDemandHourCap": 12,
    "portalHomeMinMs": 900, "portalHomeMaxMs": 1800,
    "portalSearchMinMs": 2000, "portalSearchMaxMs": 3200,
    "scrollPxMin": 500, "scrollPxMax": 820,
    "scrollWaitMinMs": 180, "scrollWaitMaxMs": 440,
    "pagesPerKeyword": 8, "readTries": 12, "readTriesPaged": 36, "readGapMs": 800,
    "blockCooldownMs": 21600000, "slowWindowMs": 86400000, "slowFactor": 2, "maxConsecutiveFail": 5,
    "heartbeatMin": 5, "logKeep": 200, "outboxMaxItems": 100, "outboxMaxAttempts": 6, "dailyDueMs": 300000,
    "extraBlockPhrases": [],
    "machinePaused": False,
    "swEarlyStop": True, "swUploadPartial": True, "swTapProbe": True,
    "swSearchEntry": None, "swCoordinated": None,
}

# ── 안전선(= remote_settings.js FENCES) — 서버는 이 선으로 미리 잘라 보낸다 ─────────
FENCES: Dict[str, tuple] = {
    "spreadMinMs": (20000, 10 * MIN), "spreadLo": (0.3, 3), "spreadHi": (0.3, 3),
    "pageGapMinMs": (800, 30000), "pageGapMaxMs": (800, 30000),
    "hourBudgetMs": (10 * MIN, 55 * MIN), "hourTailMs": (2 * MIN, 20 * MIN),
    "onDemandGapMs": (15000, 10 * MIN), "onDemandHourCap": (0, 20),
    "portalHomeMinMs": (500, 15000), "portalHomeMaxMs": (500, 15000),
    "portalSearchMinMs": (500, 15000), "portalSearchMaxMs": (500, 15000),
    "scrollPxMin": (200, 1500), "scrollPxMax": (200, 1500),
    "scrollWaitMinMs": (100, 3000), "scrollWaitMaxMs": (100, 3000),
    "pagesPerKeyword": (1, 10), "readTries": (5, 40), "readTriesPaged": (5, 60), "readGapMs": (300, 3000),
    "blockCooldownMs": (1 * HOUR, 48 * HOUR), "slowWindowMs": (0, 72 * HOUR), "slowFactor": (1, 5),
    "maxConsecutiveFail": (1, 10),
    "heartbeatMin": (1, 30), "logKeep": (50, 1000), "outboxMaxItems": (20, 300), "outboxMaxAttempts": (1, 12),
    "dailyDueMs": (1 * MIN, 30 * MIN),
}
INTEGER_KEYS = ("onDemandHourCap", "pagesPerKeyword", "readTries", "readTriesPaged", "maxConsecutiveFail",
                "heartbeatMin", "logKeep", "outboxMaxItems", "outboxMaxAttempts")
PAIRS = (("spreadLo", "spreadHi"), ("pageGapMinMs", "pageGapMaxMs"),
         ("portalHomeMinMs", "portalHomeMaxMs"), ("portalSearchMinMs", "portalSearchMaxMs"),
         ("scrollPxMin", "scrollPxMax"), ("scrollWaitMinMs", "scrollWaitMaxMs"))
COMMAND_KINDS = ("runNow", "rearmAlarms", "flushOutbox", "uploadLogs", "uploadDiag")

# ── 지금 적용할 값 ─────────────────────────────────────────────────────────────
# 두 대 모두에 적용. 비어 있으면 = 기본값 그대로(교체 첫날 동작 변화 0).
SETTINGS: Dict[str, Any] = {}

# 기계별 덮어쓰기 — {기계 번호(1부터): {칸: 값}}. 비어 있으면 두 대가 같은 값.
WORKER_OVERRIDES: Dict[int, Dict[str, Any]] = {}

# 기계 배정 — {instanceId: {"no": 번호, "count": 전체 대수}}. 비어 있으면 팝업 값 그대로.
# instanceId 는 수집기가 스스로 만든 무작위 id(로직분석 화면 「수집기 운영」 패널에 보인다).
ASSIGNMENTS: Dict[str, Dict[str, int]] = {}

# 한 번만 시키는 명령 — [{"id", "kind", "until"(ISO, 이 시각 뒤엔 무시), "worker"(번호 · None=모두)}]
# ⚠️ 캡차 쉼을 푸는 명령은 없다(대표 확정 ④).
COMMANDS: List[Dict[str, Any]] = []


def _clamp_values(values: Dict[str, Any]) -> Dict[str, Any]:
    """수집기(remote_settings.merge)와 같은 규칙으로 자른다 — 모르는 칸은 버린다."""
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (values or {}).items():
        if k not in DEFAULTS:
            continue
        if k in FENCES:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            # ⚠️ 파이썬 round 는 2.5→2(은행가 반올림)라 수집기 Math.round(2.5→3)와 어긋난다 → floor(x+0.5)
            x = int(math.floor(v + 0.5)) if k in INTEGER_KEYS else v
            lo, hi = FENCES[k]
            out[k] = lo if x < lo else (hi if x > hi else x)
        elif k in ("machinePaused", "swEarlyStop", "swUploadPartial", "swTapProbe"):
            if isinstance(v, bool):
                out[k] = v
        elif k in ("swSearchEntry", "swCoordinated"):
            if v is None or isinstance(v, bool):
                out[k] = v
        elif k == "extraBlockPhrases":
            if isinstance(v, list):
                ph: List[str] = []
                for s in v:
                    if isinstance(s, str) and 2 <= len(s.strip()) <= 60 and s.strip() not in ph and len(ph) < 20:
                        ph.append(s.strip())
                out[k] = ph
    for lo, hi in PAIRS:
        if out[lo] > out[hi]:
            out[hi] = out[lo]
    return out


def config_fingerprint() -> str:
    """SETTINGS·WORKER_OVERRIDES 원문의 지문 — REV_LEDGER 대조용(값을 바꿨는데 번호를 안 올렸는지)."""
    canon = json.dumps({"s": SETTINGS, "w": {str(k): v for k, v in WORKER_OVERRIDES.items()}},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:8]


def _fingerprint(values: Dict[str, Any]) -> str:
    """설정 지문 — 수집기가 적용한 값과 서버가 보낸 값이 같은지 화면에서 대조한다."""
    canon = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:8]


def values_for(worker_no: Optional[int]) -> Dict[str, Any]:
    merged = dict(SETTINGS)
    try:
        if worker_no is not None:
            merged.update(WORKER_OVERRIDES.get(int(worker_no), {}))
    except (TypeError, ValueError):
        pass
    return _clamp_values(merged)


def assignment_for(instance_id: Optional[str]) -> Optional[Dict[str, int]]:
    """서버가 정한 기계 번호. 없거나 형식이 틀리면 None(= 팝업 값 그대로)."""
    iid = str(instance_id or "").strip()
    if not iid or iid not in ASSIGNMENTS:
        return None
    try:
        a = ASSIGNMENTS[iid]
        no, cnt = int(a.get("no", 0)), int(a.get("count", 0))
    except (TypeError, ValueError, AttributeError):
        return None
    if 1 <= cnt <= 5 and 1 <= no <= cnt:
        return {"no": no, "count": cnt}
    return None


def settings_for(worker_no: Optional[int] = None, instance_id: Optional[str] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """응답에 싣는 설정 묶음. 실패해도 예외를 내지 않는다 — 문제가 있으면 None(수집기는 마지막 값 유지)."""
    try:
        assign = assignment_for(instance_id)
        if assign:
            worker_no = assign["no"]          # 서버가 번호를 정했으면 기계별 덮어쓰기도 그 번호로
        vals = values_for(worker_no)
        out: Dict[str, Any] = {"rev": SETTINGS_REV, "hash": _fingerprint(vals), "values": vals}
        if assign:
            out["assign"] = assign
        n = now or datetime.now()
        cmds = []
        for c in COMMANDS:
            if c.get("kind") not in COMMAND_KINDS:
                continue
            w = c.get("worker")
            if w is not None and worker_no is not None and int(w) != int(worker_no):
                continue
            try:
                until = datetime.fromisoformat(str(c.get("until")))
                if until.tzinfo is not None:          # "+09:00" 이 붙어 오면 서버 지역 시각으로 맞춘다
                    until = until.astimezone().replace(tzinfo=None)
                if until < n:
                    continue
            except (ValueError, TypeError):
                continue
            cmds.append({"id": str(c["id"]), "kind": c["kind"], "until": str(c["until"])})
        if cmds:
            out["commands"] = cmds
        return out
    except Exception:
        return None


def expected_hash(worker_no: Optional[int]) -> str:
    try:
        return _fingerprint(values_for(worker_no))
    except Exception:
        return ""


def match_text(applied_rev: Any, applied_hash: Any, worker_no: Optional[int]) -> str:
    """화면용 한 줄 — 수집기가 지금 서버 설정을 쓰고 있나."""
    ah = str(applied_hash or "")
    if not ah:
        return "설정 미보고(v1.27.0 이전 수집기)"
    if ah == expected_hash(worker_no):
        return f"⚙ {applied_rev}번 적용됨"
    return f"⚙ {applied_rev or '?'}번 → {SETTINGS_REV}번 대기(다음 신호에 맞춰짐)"
