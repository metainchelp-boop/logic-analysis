"""순위 추적 3탭 — 출처 축 집계 (대표 확정 2026-09-22 · 시안 v1)

탭 = 출처 필터.
  · 로직분석 대표 키워드 축 = clients.main_keywords (업체축 · 자동 · client_rank_history 이력)
  · 담당자 추가 키워드 축   = rank_link 로 이어진 tracked_products 의 tracked_keywords
                              (내려진 상품(disabled_at)은 제외 — 2026-09-22 소프트 내리기와 같은 규칙)
  · 전체 = 두 축 합집합(기존 rank_overview 값 그대로).

⚠️ stdlib 만 쓴다 — 배포 게이트에 fastapi 가 없어 이 모듈은 가짜 DB 로 직접 시험한다.
⚠️ 한 키워드가 두 축에 다 있으면 **두 축 모두**에 센다(각 탭이 자기 축만 보여야 하므로).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set


def norm(k) -> str:
    """키워드 비교 키 — 공백 변형·대소문자를 무시한다(rank_board 의 _norm 과 같은 규칙)."""
    return "".join(str(k or "").split()).lower()


def _has_column(conn, table: str, col: str) -> bool:
    try:
        return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return False


def registered_axes(conn, client_ids: Iterable[int]) -> Dict[int, dict]:
    """업체별 등록 축 — 어느 탭에 속하는지와 등록 키워드 수의 근거.

    반환: {cid: {"auto_kws": set[norm], "manual_kws": set[norm], "manual_products": int,
                 "contract_stage": str, "eligible": bool|None}}
      · eligible = 추적 자격(진행중·자동 추적 켜짐 …, tracking_eligibility.ELIGIBLE_WHERE).
        판정 자체가 실패하면 None(모름) — 화면은 None 이면 「대표 키워드 있음」으로 대신 가른다.
    조회가 하나 실패해도 나머지는 채운다(화면이 죽는 쪽이 더 나쁜 고장).
    """
    ids: List[int] = [int(i) for i in client_ids]
    out: Dict[int, dict] = {
        cid: {"auto_kws": set(), "manual_kws": set(), "manual_products": 0,
              "contract_stage": "", "eligible": None}
        for cid in ids}
    if not ids:
        return out
    ph = ",".join("?" * len(ids))

    # ① 대표 키워드(업체축)
    try:
        for r in conn.execute(
                f"SELECT id, COALESCE(main_keywords,'') AS mk FROM clients WHERE id IN ({ph})", ids):
            out[r[0]]["auto_kws"] = {norm(k) for k in str(r[1]).split(",") if k.strip()}
    except Exception:
        pass

    # ② 계약 단계 — 칸이 없는 옛 DB 면 비워 둔다
    if _has_column(conn, "clients", "contract_stage"):
        try:
            for r in conn.execute(
                    f"SELECT id, COALESCE(contract_stage,'') FROM clients WHERE id IN ({ph})", ids):
                out[r[0]]["contract_stage"] = (r[1] or "").strip()
        except Exception:
            pass

    # ③ 추적 자격 — 수집기와 같은 판정(진행중만). 실패하면 None 으로 둔다(0 이 아니라 「못 쟀다」).
    try:
        from tracking_eligibility import ELIGIBLE_WHERE
        elig = {r[0] for r in conn.execute(
            f"SELECT id FROM clients WHERE {ELIGIBLE_WHERE} AND id IN ({ph})", ids)}
        for cid in ids:
            out[cid]["eligible"] = cid in elig
    except Exception:
        pass

    # ④ 담당자 추가 키워드(상품축) — 이어진 상품 중 내려지지 않은 것만
    try:
        alive = "AND COALESCE(p.disabled_at,'')='' " if _has_column(conn, "tracked_products", "disabled_at") else ""
        seen_products: Dict[int, Set[int]] = {cid: set() for cid in ids}
        for r in conn.execute(
                f"SELECT l.client_id, p.id, COALESCE(k.keyword,'') "
                f"FROM rank_link l JOIN tracked_products p ON p.id = l.tracked_product_id "
                f"LEFT JOIN tracked_keywords k ON k.product_id = p.id "
                f"WHERE l.client_id IN ({ph}) {alive}", ids):
            cid = r[0]
            if cid not in out:
                continue
            seen_products[cid].add(r[1])
            if str(r[2]).strip():
                out[cid]["manual_kws"].add(norm(r[2]))
        for cid in ids:
            out[cid]["manual_products"] = len(seen_products[cid])
    except Exception:
        pass
    return out


def new_stat() -> dict:
    return {"keywords": 0, "exposed": 0, "top10": 0, "up": 0, "down": 0, "last_checked": ""}


def add_stat(stat: dict, latest: Optional[int], prev: Optional[int], latest_d: str) -> None:
    """(업체, 키워드) 하나의 최신/전일 값을 집계에 더한다 — rank_overview 의 규칙 그대로."""
    stat["keywords"] += 1
    if latest is not None:
        stat["exposed"] += 1
        if latest <= 10:
            stat["top10"] += 1
    if latest is not None and prev is not None:
        if latest < prev:
            stat["up"] += 1
        elif latest > prev:
            stat["down"] += 1
    if latest_d and latest_d > stat["last_checked"]:
        stat["last_checked"] = latest_d


def axes_payload(reg: dict, client_stat: Optional[dict], product_stat: Optional[dict]) -> dict:
    """화면이 읽는 모양. registered 는 등록 수(이력이 없어도 「첫 수집 대기」로 셀 근거)."""
    c = dict(client_stat or new_stat()); c["registered"] = len(reg.get("auto_kws") or ())
    p = dict(product_stat or new_stat()); p["registered"] = len(reg.get("manual_kws") or ())
    p["products"] = int(reg.get("manual_products") or 0)
    return {"client": c, "product": p}


def in_tab(item: dict, tab: str) -> bool:
    """탭 소속 판정(서버·시험 공용 — 화면 JS 와 같은 규칙).
    auto   = 추적 자격 있는 업체(자격을 못 쟀으면 대표 키워드 있는 업체)
    manual = 살아 있는 이어진 상품이 하나라도 있는 업체
    all    = 전부
    """
    if tab == "auto":
        if item.get("eligible") is None:
            return int(item.get("auto_keywords") or 0) > 0
        return bool(item.get("eligible"))
    if tab == "manual":
        return int(item.get("manual_products") or 0) > 0
    return True
