"""수집 관측 원장 — 코덱스 1.22.0 `collector_observation` 이식판 (2026-09-22 · 수집기 자체 개발 2차)

코덱스 원안에서 가져온 것
  · 업로드마다 **관측 봉투**(observationId·workerId·status·stopReason·pagesRead·pageEvidence·coveredThroughRank·targetIds)를
    검증하고, 원문 해시와 함께 `collector_observations` 에 남긴다(같은 observationId 재전송은 한 번만 반영).
  · **부분 관측은 양성만** — 300위까지 안 본 업로드(막힘·조기 종료)는 찾은 순위만 적고 「없다(300위 밖)」는 적지 않는다.
  · 「시도했지만 완료 못 한」 키워드를 `/keywords` 가 뒤로 돌리는 근거(attempted_map).

코덱스 원안과 **일부러 다르게** 한 것(검토 보고 B3·B4·B6 해소)
  · 봉투가 없거나(구확장 v1.21 이하) 봉투가 어긋나면 **격리하지 않고 종전 경로 그대로** 저장한다(fail-open).
    원안은 LEGACY_UNVERIFIED 로 격리해 순위에 안 실었다 — 「조용히 멈추는 쪽이 더 나쁜 고장」 원칙과 반대.
  · `target_complete`(목표를 다 찾아 조기 종료)는 수집분(collected_serp)은 저장하되 순위는 양성만 적는다 —
    원안은 수집분도 안 남겨 같은 키워드를 다시 돌게 했다(조기 종료 절감 80% 가 사라짐).
  · 삭제 금지 트리거를 두지 않고 **30일 보관정책**을 둔다(원안은 무한 증식 · 검토 보고 major).
  · 이 모듈은 DB 쓰기를 **호출자가 넘긴 함수**로 한다 — fastapi 없이 가짜 DB 로 시험한다.

⚠️ stdlib 만.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
from uuid import UUID

MAX_PRODUCTS = 1000
MAX_PAGES = 30
RETENTION_DAYS = 30
STATUSES = {"complete", "target_complete", "partial", "failed", "paused"}
SOURCES = {"tap", "router", "nextdata"}

# kind — 서버가 무엇을 하는가
#   full            수집분 저장 + 전 대상 순위 기록(300위 밖 포함)  ← 종전 경로 · legacy · complete
#   full_positive   수집분 저장 + 찾은 순위만                        ← target_complete
#   positive        수집분 미저장 + 찾은 순위만                      ← partial
#   evidence_only   기록만                                           ← failed · paused · 상품 0건
KINDS = ("full", "full_positive", "positive", "evidence_only")


class ObservationError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _uuid_ok(v: Any) -> bool:
    try:
        return isinstance(v, str) and len(v) <= 36 and str(UUID(v)) == v.lower()
    except ValueError:
        return False


def _ts(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:
        return None


def _envelope_problem(obs: Any, keyword: str, n_products: int) -> str:
    """봉투가 어긋난 이유 한 마디. 빈 문자열이면 정상."""
    if not isinstance(obs, dict):
        return "not-object"
    if obs.get("schemaVersion") != 1:
        return "schemaVersion"
    if not _uuid_ok(obs.get("observationId")):
        return "observationId"
    if (obs.get("keyword") or "").strip() != keyword:
        return "keyword-mismatch"
    if obs.get("status") not in STATUSES:
        return "status"
    s, f = _ts(obs.get("startedAt")), _ts(obs.get("finishedAt"))
    if not s or not f or f < s or f - s > timedelta(hours=24) or f > datetime.now(timezone.utc) + timedelta(minutes=5):
        return "times"
    for k in ("requestedDepth", "pagesRead", "organicCount", "coveredThroughRank"):
        v = obs.get(k)
        if type(v) is not int or v < 0 or v > MAX_PRODUCTS:
            return k
    if obs["pagesRead"] > MAX_PAGES:
        return "pagesRead"
    if obs["organicCount"] != n_products:
        return "organicCount"
    ev = obs.get("pageEvidence")
    if not isinstance(ev, list) or len(ev) != obs["pagesRead"]:
        return "pageEvidence-count"
    for i, e in enumerate(ev, 1):
        if (not isinstance(e, dict) or e.get("page") != i or e.get("verified") is not True
                or e.get("source") not in SOURCES or (e.get("keyword") or "") != keyword):
            return f"pageEvidence[{i}]"
    t = obs.get("targetIds")
    if not isinstance(t, list) or len(t) > MAX_PRODUCTS or len(set(map(str, t))) != len(t):
        return "targetIds"
    return ""


def validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """업로드 본문을 판정한다. 봉투 오류는 **거절하지 않고** legacy 로 내린다(fail-open).

    반환 = {keyword, products, meta, payload_hash, products_json, observation, observation_id,
            status, kind, reason}
    """
    if not isinstance(payload, dict):
        raise ObservationError("INVALID_BODY", "본문이 객체가 아닙니다", 400)
    kw = str(payload.get("keyword") or "").strip()
    if not kw:
        raise ObservationError("EMPTY_KEYWORD", "keyword 가 비어 있습니다.", 400)
    products = payload.get("products")
    if not isinstance(products, list):
        raise ObservationError("INVALID_PRODUCTS", "products 가 목록이 아닙니다.", 400)
    if len(products) > MAX_PRODUCTS:
        raise ObservationError("TOO_MANY_PRODUCTS", f"상품 {len(products)}건 — 상한 {MAX_PRODUCTS}", 413)
    meta = payload.get("meta")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ObservationError("INVALID_META", "meta 가 객체가 아닙니다.", 400)
    body = canonical({"keyword": kw, "total": payload.get("total", 0), "products": products, "meta": meta})
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    out = {"keyword": kw, "products": products, "meta": meta, "payload_hash": digest,
           "products_json": canonical(products), "observation": None,
           "observation_id": "legacy:" + digest, "status": "legacy", "kind": "full", "reason": "LEGACY"}
    if "observation" not in meta:
        return out                                       # v1.21 이하 확장 — 종전 경로 그대로
    obs = meta.get("observation")
    why = _envelope_problem(obs, kw, len(products))
    if why:
        out["reason"] = "ENVELOPE_INVALID:" + why        # 격리하지 않는다 — 종전 경로 + 사유 기록
        return out
    status = obs["status"]
    if status == "complete":
        kind, reason = "full", "COMPLETE"
    elif status == "target_complete":
        kind, reason = "full_positive", "TARGETS_FOUND"
    elif status == "partial":
        kind, reason = ("positive" if products else "evidence_only"), str(obs.get("stopReason") or "PARTIAL")[:60]
    else:                                                # failed · paused
        kind, reason = "evidence_only", str(obs.get("stopReason") or status)[:60]
    out.update(observation=obs, observation_id=obs["observationId"].lower(), status=status, kind=kind, reason=reason)
    return out


DDL = """
CREATE TABLE IF NOT EXISTS collector_observations (
    observation_id TEXT PRIMARY KEY,
    keyword        TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    status         TEXT NOT NULL,
    kind           TEXT NOT NULL,
    reason         TEXT DEFAULT '',
    payload_hash   TEXT NOT NULL,
    products_json  TEXT NOT NULL,
    meta_json      TEXT NOT NULL,
    projected      INTEGER NOT NULL DEFAULT 0,
    result_json    TEXT NOT NULL,
    received_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_collector_observations_kw ON collector_observations(keyword, received_at);
CREATE INDEX IF NOT EXISTS idx_collector_observations_day ON collector_observations(collected_date);
-- 원문은 고치지 않는다(증거). 지우는 것은 보관정책(purge_old)만 한다 — 삭제 금지 트리거는 일부러 두지 않았다.
CREATE TRIGGER IF NOT EXISTS collector_observations_no_update
    BEFORE UPDATE ON collector_observations
    BEGIN SELECT RAISE(ABORT, 'collector observations are immutable'); END;
"""


def init_observation_db(conn) -> None:
    conn.executescript(DDL)
    conn.commit()


def purge_old(conn, days: int = RETENTION_DAYS) -> int:
    """보관정책 — days 일 지난 관측 원문을 지운다. 실패하면 0 이 아니라 -1(못 쟀다)."""
    try:
        cur = conn.execute("DELETE FROM collector_observations WHERE received_at < datetime('now','localtime', ?)",
                           (f"-{int(days)} day",))
        conn.commit()
        return cur.rowcount if cur.rowcount is not None else 0
    except Exception:
        return -1


def ingest(conn, item: Dict[str, Any], collected_date: str,
           store_full: Callable[[bool], Dict[str, int]],
           project_positive: Callable[[], Dict[str, int]]) -> Dict[str, Any]:
    """판정된 업로드 1건을 반영한다.

    store_full(positive_only) — 수집분 저장 + 큐 완료 + 순위 기록(positive_only 면 찾은 것만). 반환 = ranked
    project_positive()        — 수집분 저장 없이 찾은 순위만. 반환 = ranked
    같은 observationId(봉투 있는 것만)가 같은 본문으로 다시 오면 저장된 결과를 그대로 돌려준다(재반영 없음).
    """
    init_observation_db(conn)
    oid, kind = item["observation_id"], item["kind"]
    if item["observation"] is not None:
        old = conn.execute("SELECT payload_hash, result_json FROM collector_observations WHERE observation_id=?",
                           (oid,)).fetchone()
        if old:
            if old[0] != item["payload_hash"]:
                raise ObservationError("OBSERVATION_ID_CONFLICT", "같은 observationId 에 다른 본문", 409)
            res = json.loads(old[1]); res["duplicate"] = True
            res.setdefault("payloadHash", item["payload_hash"]); res.setdefault("protocol", 2)   # 4차 ACK 대조용
            return res
    ranked = {"products": 0, "clients": 0}
    if kind == "full":
        ranked = store_full(False) or ranked
    elif kind == "full_positive":
        ranked = store_full(True) or ranked
    elif kind == "positive":
        ranked = project_positive() or ranked
    projected = kind in ("full", "full_positive")
    result = {"success": True, "stored": True, "keyword": item["keyword"], "saved": len(item["products"]),
              "projected": projected, "projectionStatus": {"full": "full", "full_positive": "full_positive",
                                                            "positive": "partial_positive"}.get(kind, "evidence_only"),
              "observationStatus": item["status"], "observationId": oid, "reason": item["reason"],
              "ranked": ranked, "duplicate": False,
              # 📤 4차(코덱스 ACK 이식) — 확장이 「내가 보낸 그 본문이 저장됐다」를 대조하는 열쇠. 구확장은 무시한다.
              "protocol": 2, "payloadHash": item["payload_hash"]}
    try:
        conn.execute("""INSERT OR IGNORE INTO collector_observations
            (observation_id, keyword, collected_date, status, kind, reason, payload_hash, products_json, meta_json, projected, result_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (oid, item["keyword"], collected_date, item["status"], kind, item["reason"][:120],
                      item["payload_hash"], item["products_json"], canonical(item["meta"]), int(projected), canonical(result)))
        conn.commit()
    except Exception:
        pass   # 원장 기록 실패가 업로드 성공을 뒤집지는 않는다(수집이 우선)
    return result


def attempted_map(conn, collected_date: str) -> Dict[str, str]:
    """오늘 「시도했지만 완료 못 한」 키워드 → 마지막 시도 시각. /keywords 가 이걸로 뒤로 돌린다."""
    try:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT keyword, MAX(received_at) FROM collector_observations "
            "WHERE collected_date=? AND projected=0 AND status NOT IN ('legacy') GROUP BY keyword",
            (collected_date,))}
    except Exception:
        return {}


def attempt_count_map(conn, collected_date: str) -> Dict[str, int]:
    """오늘 「시도했지만 완료 못 한」 횟수 — {키워드: 횟수}. attempted_map 과 같은 행을 센다.

    🌙 밤 재시도 상한(대표 확정 2026-09-24 · collect_order.night_retry_capped)의 근거.
    실패하면 빈 dict = 거르지 않음(종전 동작).
    """
    try:
        return {r[0]: int(r[1] or 0) for r in conn.execute(
            "SELECT keyword, COUNT(*) FROM collector_observations "
            "WHERE collected_date=? AND projected=0 AND status NOT IN ('legacy') GROUP BY keyword",
            (collected_date,))}
    except Exception:
        return {}


def observation_summary(conn, collected_date: str) -> Dict[str, Any]:
    try:
        counts = [{"status": r[0], "kind": r[1], "count": r[2]} for r in conn.execute(
            "SELECT status, kind, COUNT(*) FROM collector_observations WHERE collected_date=? GROUP BY status, kind",
            (collected_date,))]
        latest = []
        for r in conn.execute("SELECT keyword, status, kind, reason, received_at, result_json FROM collector_observations "
                              "ORDER BY received_at DESC, rowid DESC LIMIT 20"):
            try:
                rk = json.loads(r[5]).get("ranked") or {}
            except Exception:
                rk = {}
            latest.append({"keyword": r[0], "status": r[1], "kind": r[2], "reason": r[3], "receivedAt": r[4], "ranked": rk})
        return {"counts": counts, "latest": latest}
    except Exception:
        return {"counts": None, "latest": None}
