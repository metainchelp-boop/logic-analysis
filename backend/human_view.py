"""관리팀 순위 읽기 도우미 — 서버 쪽 규칙 (2026-09-24 · 대표 확정 4건)

왜 만들었나
  수집기(자동)는 2페이지부터 네이버에 막힌다(기계 클릭 418 · 사람 클릭 200 — 같은 기계·같은 회선 실측).
  9/24 부분 수집 348개 중 약 300개는 1페이지(40위)에서 추적 대상이 안 보였다 — 41~300위를 볼 길이 없다.
  그래서 **관리팀 직원이 업무 중에 직접 넘긴 네이버쇼핑 화면**을 옆에서 읽어 그 몫을 채운다.
  읽기 전용이다 — 확장은 네이버에 요청을 하나도 보내지 않는다(검색·클릭·페이지 넘김 전부 사람).

대표 확정(2026-09-24 시안 https://claude.ai/artifact/JAstDtTWcCwxBqugYGBeqN)
  ① 할 일 목록을 보여 준다        → todo()
  ② 1인당 하루 목표는 없다        → 목표·할당 칸을 두지 않는다
  ③ 운영 화면에는 PC 번호만       → 직원 이름·계정을 받지도 저장하지도 않는다
  ④ 로그인한 화면도 읽는다 · 첫 주 대조 후 결정
                                  → 로그인 여부(in/out/unknown)를 같이 받아 두고 login_compare() 로 대조한다.
                                    대조 결과 차이가 크면 LOGGED_IN_RECORD 를 False 로 내린다(로그아웃 창만 기록).

규칙(수집기와 같다 — 한 규칙 여러 입구)
  · 순위는 **1위부터 끊김 없이 본 만큼만** 받는다(확장이 1페이지부터 이어 본 것만 올린다 · 서버가 다시 확인).
  · 300위까지 봤거나 결과 끝까지 봤으면 **완료** — 못 찾은 대상은 「300위 밖」으로 적는다(수집기 전량과 같다).
  · 그 전이면 **찾은 순위만** 적는다(「없다」는 못 적는다). 추적 대상을 전부 찾았으면 그날 완료(collector_found_done).
  · 우리 추적 키워드(수집 유니버스)가 아니면 **아무것도 저장하지 않는다**(직원 검색 기록을 남기지 않는다).

⚠️ stdlib 만 — 게이트 환경에는 fastapi 가 없다. 라우트는 human_view_routes.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable, Dict, Iterable, List, Optional

TOKEN_LABEL = b"human-view-v1"
MAX_DEPTH = 300            # 수집기와 같은 깊이(대표 확정 2026-09-18)
MAX_PAGES = 15             # 40개씩 8장이면 300위 — 여유를 둔다
MAX_PC = 99
RETENTION_DAYS = 30
BUSY_MINUTES = 10          # 다른 PC 가 방금 본 키워드는 「확인 중」으로 표시(할 일 목록에서 겹치지 않게)
LOGIN_STATES = ("in", "out", "unknown")
# ④ 첫 주 대조 — 로그인한 화면도 기록한다. 대조(login_compare)에서 차이가 크면 False 로 내린다.
LOGGED_IN_RECORD = True


class HumanViewError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


# ── 인증 ────────────────────────────────────────────────────────────────
def derive_token(collector_token: str) -> str:
    """수집기 토큰에서 **다른** 토큰을 뽑는다 — 관리팀 PC 에 수집기 토큰을 주지 않기 위함.
    이 토큰으로는 /api/collector/* 를 못 부른다(값이 다르다). 수집기 토큰이 없으면 빈 값 = 전 경로 막힘."""
    if not collector_token:
        return ""
    return hmac.new(collector_token.encode("utf-8"), TOKEN_LABEL, hashlib.sha256).hexdigest()[:40]


def token_ok(provided: Optional[str], collector_token: str) -> bool:
    want = derive_token(collector_token)
    if not want or not provided:
        return False
    return hmac.compare_digest(str(provided), want)


def pc_no(v: Any) -> int:
    """PC 번호(1~99). 이름·계정은 받지 않는다(대표 확정 ③)."""
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise HumanViewError("PC 번호가 없습니다 — 팝업에서 PC 번호를 넣어 주세요.", 400)
    if n < 1 or n > MAX_PC:
        raise HumanViewError(f"PC 번호는 1~{MAX_PC} 입니다.", 400)
    return n


# ── 업로드 검증 ──────────────────────────────────────────────────────────
def validate(body: Dict[str, Any]) -> Dict[str, Any]:
    """확장이 올린 한 건을 판정한다. 틀린 것은 저장하지 않고 거절한다(사람 화면이라 다시 보면 된다)."""
    if not isinstance(body, dict):
        raise HumanViewError("본문이 객체가 아닙니다.", 400)
    kw = str(body.get("keyword") or "").strip()
    if not kw or len(kw) > 120:
        raise HumanViewError("검색어가 비었거나 너무 깁니다.", 400)
    products = body.get("products")
    if not isinstance(products, list) or not products:
        raise HumanViewError("상품이 0건입니다.", 400)
    if len(products) > MAX_DEPTH + 60:
        raise HumanViewError("상품이 너무 많습니다.", 413)
    pages = body.get("pagesRead")
    if type(pages) is not int or pages < 1 or pages > MAX_PAGES:
        raise HumanViewError("pagesRead 가 1~15 가 아닙니다.", 400)
    # 1위부터 끊김 없이 — 중간 페이지만 본 화면으로는 순위를 매길 수 없다(앞 페이지 오가닉 수를 모른다).
    seen = set()
    for i, p in enumerate(products, 1):
        if not isinstance(p, dict):
            raise HumanViewError("상품 형식이 틀렸습니다.", 400)
        if p.get("rank") != i:
            raise HumanViewError(f"순위가 1위부터 이어지지 않습니다({i}번째).", 422)
        pid = str(p.get("productId") or "").strip()
        if not pid:
            raise HumanViewError("상품 번호가 빈 줄이 있습니다.", 422)
        if pid in seen:
            raise HumanViewError("같은 상품이 두 번 들어 있습니다.", 422)
        seen.add(pid)
    products = products[:MAX_DEPTH]
    end = body.get("endOfResults") is True
    login = body.get("loggedIn")
    if login not in LOGIN_STATES:
        login = "unknown"
    complete = end or len(products) >= MAX_DEPTH
    return {"keyword": kw, "products": products, "pages": pages, "covered": len(products),
            "end": end, "complete": complete, "loggedIn": login,
            "extVersion": str(body.get("extVersion") or "")[:20]}


def records_rank(item: Dict[str, Any]) -> bool:
    """이 화면으로 순위를 적는가 — ④ 첫 주 대조 결과에 따라 로그인 화면을 뺄 수 있게 한 곳에 둔다."""
    if item.get("loggedIn") == "in" and not LOGGED_IN_RECORD:
        return False
    return True


# ── 저장 ────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS human_view_uploads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword          TEXT NOT NULL,
    collected_date   TEXT NOT NULL,
    pc               INTEGER NOT NULL,
    pages_read       INTEGER NOT NULL,
    covered          INTEGER NOT NULL,
    end_of_results   INTEGER NOT NULL DEFAULT 0,
    complete         INTEGER NOT NULL DEFAULT 0,
    logged_in        TEXT NOT NULL DEFAULT 'unknown',
    recorded         INTEGER NOT NULL DEFAULT 0,
    targets_total    INTEGER NOT NULL DEFAULT 0,
    targets_found    INTEGER NOT NULL DEFAULT 0,
    top_ids          TEXT NOT NULL DEFAULT '[]',
    ext_version      TEXT DEFAULT '',
    received_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_human_view_day ON human_view_uploads(collected_date, keyword);
"""


def init_db(conn) -> None:
    conn.executescript(DDL)
    conn.commit()


def purge_old(conn, days: int = RETENTION_DAYS) -> int:
    """보관정책 — 실패하면 -1(못 쟀다). 0 과 섞지 않는다."""
    try:
        cur = conn.execute("DELETE FROM human_view_uploads WHERE received_at < datetime('now','localtime', ?)",
                           (f"-{int(days)} day",))
        conn.commit()
        return cur.rowcount if cur.rowcount is not None else 0
    except Exception:
        return -1


def _ids(products: Iterable[Dict[str, Any]], n: int = 40) -> List[str]:
    out = []
    for p in products:
        pid = str(p.get("nvMid") or p.get("productId") or "").strip()
        if pid:
            out.append(pid)
        if len(out) >= n:
            break
    return out


def ingest(conn, item: Dict[str, Any], collected_date: str, pc: int,
           record: Callable[[bool], Dict[str, int]],
           store_full: Callable[[], None]) -> Dict[str, Any]:
    """판정된 한 건을 반영한다.

    record(positive_only) — 순위 기록(rank_record.record_ranks_for_keyword 를 감싼 것). 반환 = ranked
    store_full()          — 완료(300위·결과 끝)일 때만 수집분(collected_serp)에 저장 → 수집기가 그날 다시 안 잰다.
    """
    init_db(conn)
    ranked: Dict[str, int] = {"products": 0, "clients": 0, "targets_total": 0, "targets_found": 0}
    recorded = records_rank(item)
    if recorded:
        ranked = record(not item["complete"]) or ranked
    status = "compare_only"
    if recorded and item["complete"]:
        try:
            store_full()
            status = "complete"
        except Exception:
            status = "complete_unsaved"      # 순위는 적었고 수집분 저장만 실패 — 수집기가 다시 재도 무해
    elif recorded:
        status = "partial"
        try:
            from collector_observation import all_targets_found
            if all_targets_found(ranked):
                conn.execute("INSERT OR IGNORE INTO collector_found_done(keyword, collected_date, observation_id, targets) "
                             "VALUES (?,?,?,?)", (item["keyword"], collected_date, f"human:pc{pc}",
                                                  int(ranked.get("targets_total") or 0)))
                conn.commit()
                status = "partial_all_found"
        except Exception:
            pass                             # 표시를 못 남기면 완료로 치지 않는다(수집기가 다시 잰다 = 종전)
    try:
        conn.execute("""INSERT INTO human_view_uploads
            (keyword, collected_date, pc, pages_read, covered, end_of_results, complete, logged_in, recorded,
             targets_total, targets_found, top_ids, ext_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (item["keyword"], collected_date, pc, item["pages"], item["covered"], int(item["end"]),
                      int(status == "complete"), item["loggedIn"], int(recorded),
                      int(ranked.get("targets_total") or 0), int(ranked.get("targets_found") or 0),
                      json.dumps(_ids(item["products"])), item["extVersion"]))
        conn.commit()
    except Exception:
        pass                                 # 기록 실패가 순위 반영을 뒤집지는 않는다
    return {"success": True, "accepted": True, "keyword": item["keyword"], "status": status,
            "covered": item["covered"], "ranked": ranked, "recorded": recorded}


# ── 할 일 목록(대표 확정 ①) ─────────────────────────────────────────────
def todo(conn, universe: Dict[str, bool], collected_date: str, done: Iterable[str],
         attempted: Dict[str, str], pc: int) -> Dict[str, Any]:
    """오늘 아직 끝나지 않은 추적 키워드 — **수집기가 해 보고 못 끝낸 것부터** 앞에 둔다.

    tried   수집기가 오늘 시도했지만 완료 못 함(대개 1페이지에서 대상이 안 보여 2페이지가 필요한 것)
    covered 오늘 사람이 이미 이어 본 범위(몇 위까지) — 「이어서 보기」
    busyPc  다른 PC 가 10분 안에 본 키워드 — 겹치지 않게 표시만(막지는 않는다)
    """
    done = set(done)
    human: Dict[str, Dict[str, Any]] = {}
    try:
        for r in conn.execute(
                "SELECT keyword, MAX(covered), "
                "       MAX(CASE WHEN received_at >= datetime('now','localtime', ?) AND pc <> ? THEN pc END) "
                "  FROM human_view_uploads WHERE collected_date=? GROUP BY keyword",
                (f"-{BUSY_MINUTES} minutes", pc, collected_date)):
            human[r[0]] = {"covered": int(r[1] or 0), "busyPc": r[2]}
    except Exception:
        human = {}
    rows = []
    for kw in universe:
        if kw in done:
            continue
        h = human.get(kw) or {}
        rows.append({"keyword": kw, "tried": kw in attempted, "covered": h.get("covered", 0),
                     "busyPc": h.get("busyPc")})
    rows.sort(key=lambda r: (0 if r["tried"] else 1, -r["covered"], r["keyword"]))
    return {"date": collected_date, "total": len(universe), "done": len(set(universe) & done),
            "todo": len(rows), "keywords": rows}


# ── 운영 화면 통계 ───────────────────────────────────────────────────────
def stats(conn, collected_date: str) -> Dict[str, Any]:
    """PC 번호별 오늘 실적 + 최근 30건 + ④ 대조. 조회가 실패하면 None(0 과 섞지 않는다)."""
    try:
        pcs = [{"pc": r[0], "uploads": r[1], "keywords": r[2], "complete": r[3] or 0, "allFound": r[4] or 0,
                "lastAt": r[5]} for r in conn.execute(
            "SELECT pc, COUNT(*), COUNT(DISTINCT keyword), "
            "       COUNT(DISTINCT CASE WHEN complete=1 THEN keyword END), "
            "       COUNT(DISTINCT CASE WHEN targets_total>0 AND targets_found>=targets_total AND recorded=1 THEN keyword END), "
            "       MAX(received_at) "
            "  FROM human_view_uploads WHERE collected_date=? GROUP BY pc ORDER BY pc", (collected_date,))]
        login = {r[0]: r[1] for r in conn.execute(
            "SELECT logged_in, COUNT(*) FROM human_view_uploads WHERE collected_date=? GROUP BY logged_in",
            (collected_date,))}
        recent = [{"keyword": r[0], "pc": r[1], "covered": r[2], "complete": bool(r[3]),
                   "found": r[4], "targets": r[5], "loggedIn": r[6], "recorded": bool(r[7]), "at": r[8]}
                  for r in conn.execute(
            "SELECT keyword, pc, covered, complete, targets_found, targets_total, logged_in, recorded, received_at "
            "  FROM human_view_uploads ORDER BY id DESC LIMIT 30")]
    except Exception:
        return {"pcs": None, "login": None, "recent": None}
    return {"pcs": pcs, "login": login, "recent": recent, "loggedInRecorded": LOGGED_IN_RECORD}


def _serp_ids(products_json: str, n: int = 40) -> List[str]:
    try:
        return _ids(json.loads(products_json or "[]"), n)
    except Exception:
        return []


def login_compare(conn, since_date: str, top: int = 20) -> Dict[str, Any]:
    """④ 첫 주 대조 — 사람 화면(로그인/비로그인)의 앞 top 개를 **같은 날 수집기 결과**와 맞춘다.

    samePos  같은 자리(같은 순위)에 같은 상품이 있는 비율
    overlap  앞 top 개 안에 같은 상품이 들어 있는 비율(순서 무시)
    로그인 화면이 비로그인보다 눈에 띄게 낮으면 개인 맞춤이 끼어든 것 → LOGGED_IN_RECORD 를 내린다.
    수집분이 없는 날·키워드는 짝이 없어 빠진다(pairs 로 표본 수를 함께 준다). 실패하면 None.
    """
    try:
        rows = conn.execute(
            "SELECT h.logged_in, h.top_ids, s.products_json FROM human_view_uploads h "
            "  JOIN collected_serp s ON s.keyword = h.keyword AND s.collected_date = h.collected_date "
            " WHERE h.collected_date >= ?", (since_date,)).fetchall()
    except Exception:
        return {"in": None, "out": None, "unknown": None}
    acc = {k: {"pairs": 0, "same": 0, "overlap": 0, "slots": 0} for k in LOGIN_STATES}
    for login, top_ids, pj in rows:
        a = json.loads(top_ids or "[]")[:top]
        b = _serp_ids(pj, top)
        n = min(len(a), len(b))
        if n < 5:
            continue
        a, b = a[:n], b[:n]
        s = acc.get(login) or acc["unknown"]
        s["pairs"] += 1
        s["slots"] += n
        s["same"] += sum(1 for x, y in zip(a, b) if x == y)
        s["overlap"] += len(set(a) & set(b))
    out = {}
    for k, s in acc.items():
        out[k] = {"pairs": s["pairs"],
                  "samePos": round(s["same"] / s["slots"], 3) if s["slots"] else None,
                  "overlap": round(s["overlap"] / s["slots"], 3) if s["slots"] else None}
    return out
