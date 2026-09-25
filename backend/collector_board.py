"""수집 현황판 — 매일 수집기 상태를 한 화면에서 본다 (대표 지시 2026-09-25)

대표 원문: 「이게 잘 작동하는지도 확인하는, 그리고 매일 수집기 관련 데이터를 확인할 수 있는 별도의 페이지를
만들어서 현황판으로 볼수 있게 개발하자. 매번 여기서 물어볼수 없어.」

지금까지 진단 워크플로(debug-rank)로 손으로 재던 것을 그대로 옮겼다 — 같은 표 · 같은 규칙:
  ① 판정 줄   진짜 차단 0 · 기계 가동 수 · 분할 겹침/누락 · 서버 설정 일치 · 미전송 · 오늘 순위 기록
  ② 오늘      완료(300위까지 본 것 + 대상 다 찾은 것) · 부분 · 아직 안 본 것 · 시도 수 · 시간대별
  ③ 14일 추이 완료 · 부분 · 진짜 차단 · 진단 보고 · 도우미 화면
  ④ 기계      heartbeat(살아있음 신호) — 3일 넘게 조용한 줄은 「옛 설치본」으로 따로 뺀다
  ⑤ 막힘 사유 진짜 차단(퍼즐·차단 문구)과 진단 보고(2페이지 불변·응답 요약)를 **갈라** 센다
  ⑥ 멈춘 이유 부분 수집이 왜 멈췄나(관측 원장 reason)
  ⑦ 순위 기록 오늘 업체 순위·추적 상품 순위가 몇 줄 적혔나
  ⑧ 도우미    순위 읽기 도우미 PC별(human_view)

⚠️ 읽기 전용 · stdlib 만 · 조회가 실패한 칸은 **None**(0 과 섞지 않는다 — 이 저장소 규칙).
⚠️ 「막힘 보고」를 이름으로 판정하지 않는다(9/18 교훈) — 사유 코드를 펼쳐 진짜 차단만 따로 센다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

HISTORY_DAYS = 14
OLD_MACHINE_DAYS = 3        # 이보다 오래 조용한 heartbeat 줄은 옛 설치본(교체 전 기록)으로 본다

# 막힘 보고 사유 — 앞머리 코드로 가른다(뒤의 괄호 설명은 확장 버전마다 다를 수 있다)
REAL_BLOCK_CODES = ("BLOCK_TEXT", "CAPTCHA", "HTTP_418", "418")
DIAG_CODES = ("STALE_PAGE", "TAP_PROBE", "NO_PAGER", "SAME_AS_PREV")
CODE_LABEL = {
    "BLOCK_TEXT": "차단 문구·퍼즐(진짜 차단)",
    "STALE_PAGE": "2페이지를 눌러도 화면 그대로(진단)",
    "TAP_PROBE": "화면이 받은 응답 요약(진단)",
    "NO_PAGER": "페이지 버튼을 못 찾음(진단)",
    "SAME_AS_PREV": "직전 키워드와 결과가 같음(진단)",
    "REDIRECT": "검색 화면을 벗어남",
}


def _q1(conn, sql, args=()) -> Optional[int]:
    try:
        r = conn.execute(sql, args).fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    except Exception:
        return None


def _has(conn, name: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    except Exception:
        return False


def code_of(err: Any) -> str:
    """'STALE_PAGE(클릭 뒤 내용 불변)' → 'STALE_PAGE'."""
    s = str(err or "").strip()
    head = s.split("(", 1)[0].strip().upper()
    return head or "UNKNOWN"


def classify(code: str) -> str:
    """real(진짜 차단) · diag(진단 보고) · other."""
    c = code.upper()
    if c in REAL_BLOCK_CODES or "CAPTCHA" in c or "418" in c:
        return "real"
    if c in DIAG_CODES:
        return "diag"
    return "other"


# ── 막힘 보고 ─────────────────────────────────────────────────────────────
def block_breakdown(conn, since: str, until: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """[since, until) 구간의 막힘 보고를 사유별로. 실패는 None."""
    try:
        if until:
            rows = conn.execute("SELECT err, COUNT(*) FROM collector_blocks WHERE at >= ? AND at < ? GROUP BY err",
                                (since, until)).fetchall()
        else:
            rows = conn.execute("SELECT err, COUNT(*) FROM collector_blocks WHERE at >= ? GROUP BY err",
                                (since,)).fetchall()
    except Exception:
        return None
    by: Dict[str, int] = {}
    for err, n in rows:
        c = code_of(err)
        by[c] = by.get(c, 0) + int(n or 0)
    out = {"real": 0, "diag": 0, "other": 0, "codes": []}
    for c, n in sorted(by.items(), key=lambda kv: -kv[1]):
        k = classify(c)
        out[k] += n
        out["codes"].append({"code": c, "kind": k, "count": n, "label": CODE_LABEL.get(c, c)})
    return out


def recent_real_blocks(conn, since: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
    """최근 진짜 차단 보고(시각·페이지·확장 버전) — 키워드는 내부 화면이라 싣는다."""
    try:
        rows = conn.execute("SELECT at, keyword, paging_index, err, ext_version FROM collector_blocks "
                            "WHERE at >= ? ORDER BY at DESC LIMIT 400", (since,)).fetchall()
    except Exception:
        return None
    out = []
    for at, kw, pg, err, ver in rows:
        if classify(code_of(err)) != "real":
            continue
        out.append({"at": at, "keyword": kw, "page": pg, "code": code_of(err), "version": ver})
        if len(out) >= limit:
            break
    return out


# ── 하루 요약 ────────────────────────────────────────────────────────────
def day_numbers(conn, day: str) -> Dict[str, Any]:
    full = _q1(conn, "SELECT COUNT(*) FROM collected_serp WHERE collected_date=?", (day,))
    found = _q1(conn, "SELECT COUNT(*) FROM collector_found_done WHERE collected_date=?", (day,)) \
        if _has(conn, "collector_found_done") else 0
    completed = _q1(conn, "SELECT COUNT(*) FROM (SELECT keyword FROM collected_serp WHERE collected_date=? "
                          "UNION SELECT keyword FROM collector_found_done WHERE collected_date=?)", (day, day)) \
        if _has(conn, "collector_found_done") else full
    partial = attempts = None
    if _has(conn, "collector_observations"):
        partial = _q1(conn, "SELECT COUNT(DISTINCT keyword) FROM collector_observations WHERE collected_date=? "
                            "AND kind='positive' AND keyword NOT IN (SELECT keyword FROM collected_serp WHERE collected_date=?)"
                            + (" AND keyword NOT IN (SELECT keyword FROM collector_found_done WHERE collected_date=?)"
                               if _has(conn, "collector_found_done") else ""),
                      (day, day, day) if _has(conn, "collector_found_done") else (day, day))
        attempts = _q1(conn, "SELECT COUNT(*) FROM collector_observations WHERE collected_date=?", (day,))
    human = _q1(conn, "SELECT COUNT(*) FROM human_view_uploads WHERE collected_date=?", (day,)) \
        if _has(conn, "human_view_uploads") else 0
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    blocks = block_breakdown(conn, day, nxt)
    return {"day": day, "completed": completed, "full": full, "found": found, "partial": partial,
            "attempts": attempts, "human": human,
            "realBlocks": blocks["real"] if blocks else None, "diagBlocks": blocks["diag"] if blocks else None}


def history(conn, today: str, days: int = HISTORY_DAYS) -> List[Dict[str, Any]]:
    t = date.fromisoformat(today)
    return [day_numbers(conn, (t - timedelta(days=i)).isoformat()) for i in range(days - 1, -1, -1)]


def hourly(conn, today: str) -> Optional[List[Dict[str, Any]]]:
    """오늘 시간대별 시도(관측 원장)·완료(수집분 + 대상 다 찾음)."""
    att = [0] * 24
    done = [0] * 24
    try:
        if _has(conn, "collector_observations"):
            for h, n in conn.execute("SELECT CAST(strftime('%H', received_at) AS INTEGER), COUNT(*) "
                                     "FROM collector_observations WHERE collected_date=? GROUP BY 1", (today,)):
                if h is not None and 0 <= int(h) < 24:
                    att[int(h)] = int(n)
        for h, n in conn.execute("SELECT CAST(strftime('%H', created_at) AS INTEGER), COUNT(*) FROM collected_serp "
                                 "WHERE collected_date=? GROUP BY 1", (today,)):
            if h is not None and 0 <= int(h) < 24:
                done[int(h)] += int(n)
        if _has(conn, "collector_found_done"):
            for h, n in conn.execute("SELECT CAST(strftime('%H', received_at) AS INTEGER), COUNT(*) FROM collector_found_done "
                                     "WHERE collected_date=? GROUP BY 1", (today,)):
                if h is not None and 0 <= int(h) < 24:
                    done[int(h)] += int(n)
    except Exception:
        return None
    return [{"hour": h, "attempts": att[h], "completed": done[h]} for h in range(24)]


def stop_reasons(conn, today: str) -> Optional[List[Dict[str, Any]]]:
    """부분 수집이 멈춘 이유(관측 원장 reason) — 완료로 반영되지 않은 시도만."""
    if not _has(conn, "collector_observations"):
        return []
    try:
        rows = conn.execute("SELECT reason, COUNT(*) FROM collector_observations WHERE collected_date=? AND projected=0 "
                            "GROUP BY reason ORDER BY 2 DESC LIMIT 12", (today,)).fetchall()
    except Exception:
        return None
    out = []
    for r, n in rows:
        reason = (r or "(없음)")[:60]
        out.append({"reason": reason, "count": int(n), "label": CODE_LABEL.get(code_of(r), "") if r else ""})
    return out


# ── 기계 · 분할 ──────────────────────────────────────────────────────────
def split_machines(rows: Optional[List[Dict[str, Any]]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """heartbeat 줄을 「지금 쓰는 기계」와 「옛 설치본」으로 가른다."""
    if rows is None:
        return {"current": None, "old": None}
    n = now or datetime.now()
    cur, old = [], []
    for r in rows:
        ms = r.get("minutes_since")
        if ms is not None and ms > OLD_MACHINE_DAYS * 24 * 60:
            old.append(r)
        else:
            cur.append(r)
    return {"current": cur, "old": old}


def split_check(keywords: Iterable[str], workers: int, split_ok) -> Optional[Dict[str, Any]]:
    """키워드를 기계 수대로 나눴을 때 기계별 몫 · 겹침 · 누락(수집기와 같은 split_rule)."""
    kws = list(keywords)
    if workers < 1:
        return None
    try:
        per = [0] * workers
        overlap = missing = 0
        for k in kws:
            owners = [w for w in range(workers) if split_ok(k, w, workers)]
            if not owners:
                missing += 1
            elif len(owners) > 1:
                overlap += 1
            for w in owners:
                per[w] += 1
        return {"workers": workers, "perWorker": per, "overlap": overlap, "missing": missing, "total": len(kws)}
    except Exception:
        return None


# ── 순위 기록 ────────────────────────────────────────────────────────────
def rank_writes(conn, today: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["clients"] = _q1(conn, "SELECT COUNT(*) FROM client_rank_history WHERE DATE(checked_at)=?", (today,)) \
        if _has(conn, "client_rank_history") else None
    out["clientsMissing"] = _q1(conn, "SELECT COUNT(*) FROM client_rank_history WHERE DATE(checked_at)=? "
                                      "AND rank_position IS NULL", (today,)) if _has(conn, "client_rank_history") else None
    out["products"] = _q1(conn, "SELECT COUNT(*) FROM rankings WHERE DATE(checked_at)=?", (today,)) \
        if _has(conn, "rankings") else None
    try:
        r = conn.execute("SELECT MAX(checked_at) FROM rankings").fetchone() if _has(conn, "rankings") else None
        out["productsLastAt"] = r[0] if r else None
    except Exception:
        out["productsLastAt"] = None
    return out


# ── 판정 줄 ──────────────────────────────────────────────────────────────
def verdicts(today_blocks: Optional[Dict[str, Any]], machines_now: Optional[List[Dict[str, Any]]],
             split: Optional[Dict[str, Any]], writes: Dict[str, Any], hour: int) -> List[Dict[str, Any]]:
    """한 줄씩 ok · warn · bad · unknown. 못 잰 것은 unknown(좋다고 치지 않는다)."""
    v: List[Dict[str, Any]] = []
    if today_blocks is None:
        v.append({"key": "block", "level": "unknown", "title": "진짜 차단", "text": "막힘 보고를 읽지 못했습니다"})
    else:
        n = today_blocks["real"]
        v.append({"key": "block", "level": "ok" if n == 0 else "bad", "title": "진짜 차단",
                  "text": "오늘 0건" if n == 0 else f"오늘 {n}건 — 퍼즐·차단 문구. 기계를 멈추고 사람이 확인하세요"})
    if machines_now is None:
        v.append({"key": "machines", "level": "unknown", "title": "수집 기계", "text": "기계 신호를 읽지 못했습니다"})
    else:
        live = [m for m in machines_now if not m.get("stale")]
        expected = max([int(m.get("worker_count") or 1) for m in machines_now] or [0])
        if not machines_now:
            v.append({"key": "machines", "level": "bad", "title": "수집 기계", "text": "신호를 보내는 기계가 없습니다"})
        else:
            level = "ok" if len(live) >= expected and expected > 0 else ("warn" if live else "bad")
            dead = [m.get("machine") for m in machines_now if m.get("stale")]
            v.append({"key": "machines", "level": level, "title": "수집 기계",
                      "text": f"{len(live)}대 가동 / {expected}대 설정" + (f" · 끊김 {', '.join(map(str, dead))}" if dead else "")})
        mism = [m.get("machine") for m in live if m.get("settingsMatch") is False]
        v.append({"key": "settings", "level": "ok" if not mism else "warn", "title": "서버 설정",
                  "text": "가동 기계 모두 최신 설정" if not mism else f"설정 대기 {', '.join(map(str, mism))}(다음 신호에 받음)"})
        pend = sum(int((m.get("uploadSummary") or {}).get("count") or 0) for m in live if isinstance(m.get("uploadSummary"), dict))
        v.append({"key": "outbox", "level": "ok" if pend == 0 else "warn", "title": "미전송",
                  "text": "쌓인 결과 없음" if pend == 0 else f"기계에 못 올린 결과 {pend}건"})
    if split is None:
        v.append({"key": "split", "level": "unknown", "title": "키워드 나누기", "text": "재지 못했습니다"})
    else:
        ok = split["overlap"] == 0 and split["missing"] == 0
        v.append({"key": "split", "level": "ok" if ok else "bad", "title": "키워드 나누기",
                  "text": (f"{split['workers']}대 · " + " · ".join(f"{i + 1}번 {n}" for i, n in enumerate(split["perWorker"]))
                           + f" · 겹침 {split['overlap']} · 누락 {split['missing']}")})
    c = writes.get("clients")
    if c is None:
        v.append({"key": "writes", "level": "unknown", "title": "오늘 순위 기록", "text": "재지 못했습니다"})
    else:
        level = "ok" if c > 0 else ("warn" if hour >= 9 else "unknown")
        v.append({"key": "writes", "level": level, "title": "오늘 순위 기록",
                  "text": f"업체 {c}줄 · 추적 상품 {writes.get('products') if writes.get('products') is not None else '미확인'}줄"})
    return v


def build(conn, today: str, universe: Optional[Iterable[str]], split_ok=None,
          machines_rows: Optional[List[Dict[str, Any]]] = None, helper: Optional[Dict[str, Any]] = None,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    n = now or datetime.now()
    uni = list(universe) if universe is not None else None     # None = 유니버스를 못 읽음(0개가 아니다)
    tb = block_breakdown(conn, today)
    m = split_machines(machines_rows, n)
    workers = max([int(r.get("worker_count") or 1) for r in (m["current"] or [])] or [1])
    sp = split_check(uni, workers, split_ok) if (split_ok and uni is not None) else None
    writes = rank_writes(conn, today)
    t = day_numbers(conn, today)
    t["universe"] = len(uni) if uni is not None else None
    t["notTried"] = None
    if t["completed"] is not None and uni is not None:
        t["notTried"] = max(0, len(uni) - (t["completed"] or 0) - (t["partial"] or 0))
    week_since = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
    return {
        "today": today, "generatedAt": n.strftime("%Y-%m-%d %H:%M:%S"),
        "verdicts": verdicts(tb, m["current"], sp, writes, n.hour),
        "summary": t,
        "hourly": hourly(conn, today),
        "history": history(conn, today),
        "blocksToday": tb,
        "blocksWeek": block_breakdown(conn, week_since),
        "recentRealBlocks": recent_real_blocks(conn, week_since),
        "stopReasons": stop_reasons(conn, today),
        "machines": m["current"], "oldMachines": m["old"],
        "split": sp,
        "rankWrites": writes,
        "helper": helper,
    }
