"""
순위 저장소 통합(C안) — 1단계: 브리지 테이블

순위 기록이 두 축으로 갈라져 있다.

  축A  tracked_products → tracked_keywords → rankings       (직원이 직접 등록한 추적 상품)
  축B  clients          → client_rank_history                (광고주 · 영업 대상 업체)

두 축은 서로를 모른다. 그래서 같은 상품이 양쪽에 따로 등록되고, 화면마다 한쪽만 읽는다
(키워드 순위 탭은 축B 만 읽는다 — 「분석 화면에서도 키워드를 추가하게 해달라」는 요청의
구조적 원인).

이 모듈은 **읽기 경로를 전혀 바꾸지 않고** 두 축을 잇는 링크만 따로 보관한다.
조회를 실제로 합치는 것은 다음 단계이고, 그 단계는 전산①이 소비하는
`/api/cd/portal-summary` 경로를 지나므로 **사전 통지 대상**이다.

실측(2026-08-05): 축A 332상품 · 축B 620업체 · 상품ID 기준 겹침 251건
(축A의 77% / 축B의 41%) · 고아 순위행 0.

매칭 규칙은 새로 만들지 않는다 — `naver_crawler.extract_product_id_from_url`
(nvMid → /products/ → /catalog/ 우선순위) 하나만 쓴다. 진단이 251건을 센 규칙과
같아야 결과가 재현되기 때문이다.
"""
import os
import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional

from naver_crawler import extract_product_id_from_url

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# 자동 매칭 근거. 어느 규칙으로 이었는지 rank_link 행마다 남는다.
MATCH_PRODUCT_ID = "product_id"      # 상품ID 정확 일치 — 가장 확실
MATCH_STORE_SLUG = "store_slug"      # 같은 스마트스토어(가게 이름) — 보조
MATCH_MANUAL = "manual"              # 화면에서 사람이 지정


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _product_key(url: str) -> str:
    """URL → 정규화 상품ID. 못 뽑으면 빈 문자열(=매칭 대상 아님)."""
    return (extract_product_id_from_url(url or "") or "").strip()


def _store_key(url: str) -> str:
    """URL → 스마트스토어 가게 이름(슬러그). 못 뽑으면 빈 문자열.

    ⚠️ 상품ID 매칭의 **보조**로만 쓴다(2026-08-27 신설).
       업체의 naver_store_url 은 '첫 등록 상품' 하나로 굳어 있어, 직원이 홈탭에서
       같은 가게의 **다른 상품**을 추적 등록하면 상품ID 가 영영 안 맞는다
       (실측: 안 이어진 116개 중 115개가 이 경우).
       같은 가게면 같은 업체이므로, 상품ID 로 못 이은 것만 여기로 내려온다.
    """
    m = re.search(r"smartstore\.naver\.com/([^/?#]+)", str(url or ""))
    if not m:
        return ""
    slug = m.group(1).strip().lower()
    # 'category' 같은 경로 조각이 가게 이름 자리에 오는 일은 없지만, 빈 값·숫자만은 거른다
    return "" if (not slug or slug.isdigit()) else slug


def init_rank_link_db():
    """브리지 테이블 생성(멱등). 기존 테이블·읽기 경로는 건드리지 않는다."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rank_link (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                tracked_product_id INTEGER NOT NULL,
                product_key TEXT NOT NULL DEFAULT '',
                match_method TEXT NOT NULL DEFAULT 'product_id',
                linked_by INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(client_id, tracked_product_id)
            );

            CREATE INDEX IF NOT EXISTS idx_rank_link_client ON rank_link(client_id);
            CREATE INDEX IF NOT EXISTS idx_rank_link_product ON rank_link(tracked_product_id);
            CREATE INDEX IF NOT EXISTS idx_rank_link_key ON rank_link(product_key);
        """)
        conn.commit()
        logger.info("[rank_link] 브리지 테이블 초기화 완료")
    except Exception as e:
        # 링크가 없어도 기존 화면은 그대로 동작한다 — 초기화 실패로 부팅을 막지 않는다.
        logger.error(f"[rank_link] 초기화 실패(무시하고 계속): {e}")
    finally:
        conn.close()


def _collect_candidates(conn: sqlite3.Connection) -> Dict[str, Any]:
    """양쪽 축을 훑어 상품ID → 행 목록으로 모은다(읽기 전용)."""
    a_by_key: Dict[str, List[Dict[str, Any]]] = {}
    a_total = a_with_key = 0
    for r in conn.execute("SELECT id, product_url, product_name, store_name FROM tracked_products"):
        a_total += 1
        key = _product_key(r["product_url"])
        if not key:
            continue
        a_with_key += 1
        a_by_key.setdefault(key, []).append(
            {"id": r["id"], "name": r["product_name"] or "", "store": r["store_name"] or ""}
        )

    # 추적 상품의 가게 이름(보조 축)
    a_by_store: Dict[str, List[Dict[str, Any]]] = {}
    for r in conn.execute("SELECT id, product_url, product_name, store_name FROM tracked_products"):
        sk = _store_key(r["product_url"])
        if sk:
            a_by_store.setdefault(sk, []).append(
                {"id": r["id"], "name": r["product_name"] or "", "store": r["store_name"] or ""}
            )

    b_by_key: Dict[str, List[Dict[str, Any]]] = {}
    b_by_store: Dict[str, List[Dict[str, Any]]] = {}
    b_total = b_with_key = 0
    for r in conn.execute(
        "SELECT id, name, naver_store_url FROM clients "
        "WHERE status='active' AND COALESCE(vertical,'store')='store'"
    ):
        b_total += 1
        row = {"id": r["id"], "name": r["name"] or ""}
        key = _product_key(r["naver_store_url"])
        if key:
            b_with_key += 1
            b_by_key.setdefault(key, []).append(row)
        sk = _store_key(r["naver_store_url"])
        if sk:
            b_by_store.setdefault(sk, []).append(row)

    # ② 키워드별 상품 등록부도 비교 대상에 넣는다 (2026-08-21 이예은 신고로 만든 표).
    #    업체 주소는 '첫 등록 상품' 하나뿐이라, 직원이 키워드마다 지정해 둔 상품은
    #    여기에만 있다. 앞으로 지정할수록 자동으로 이어지는 몫이 늘어난다.
    try:
        for r in conn.execute(
            "SELECT p.client_id AS cid, p.product_url AS url, c.name AS cname "
            "  FROM client_keyword_product p JOIN clients c ON c.id = p.client_id "
            " WHERE c.status='active' AND COALESCE(c.vertical,'store')='store'"
        ):
            row = {"id": r["cid"], "name": r["cname"] or ""}
            key = _product_key(r["url"])
            if key and not any(x["id"] == row["id"] for x in b_by_key.get(key, [])):
                b_by_key.setdefault(key, []).append(row)
            sk = _store_key(r["url"])
            if sk and not any(x["id"] == row["id"] for x in b_by_store.get(sk, [])):
                b_by_store.setdefault(sk, []).append(row)
    except Exception as e:
        # 표가 아직 없는 구버전 DB — 종전 동작(상품ID 축만)
        logger.warning(f"[rank_link] 키워드별 상품 등록부 조회 건너뜀: {e}")

    return {
        "a_by_key": a_by_key, "b_by_key": b_by_key,
        "a_by_store": a_by_store, "b_by_store": b_by_store,
        "a_total": a_total, "a_with_key": a_with_key,
        "b_total": b_total, "b_with_key": b_with_key,
    }


def _pairs(cand: Dict[str, Any]) -> List[Dict[str, Any]]:
    """양쪽에 같은 상품ID가 있는 조합을 전부 만든다.

    같은 URL이 직원별로 따로 등록될 수 있어(tracked_products는 (url, user_id) UNIQUE)
    한 업체가 여러 추적 상품과 이어질 수 있다 — 그 조합을 다 남긴다.
    """
    out = []
    a_by_key, b_by_key = cand["a_by_key"], cand["b_by_key"]

    # ① 1순위 — 상품ID 정확 일치. 가장 확실한 근거다.
    matched_products = set()
    for key in sorted(set(a_by_key) & set(b_by_key)):
        for b in b_by_key[key]:
            for a in a_by_key[key]:
                matched_products.add(a["id"])
                out.append({
                    "client_id": b["id"], "client_name": b["name"],
                    "tracked_product_id": a["id"], "product_name": a["name"],
                    "store_name": a["store"], "product_key": key,
                    "match_method": MATCH_PRODUCT_ID,
                })

    # ② 2순위 — 같은 스마트스토어(가게 이름). 상품ID 로 못 이은 것만 내려온다.
    #    ⚠️ 이미 상품ID 로 이어진 상품은 건드리지 않는다 — 더 확실한 근거를 덮지 않는다.
    #    ⚠️ 한 가게에 업체가 여럿 잡히면 **잇지 않는다.** 어느 쪽인지 모르는 채로
    #       붙이면 남의 업체 순위가 섞인다 — 그건 화면에서 사람이 고르게 둔다.
    a_by_store = cand.get("a_by_store") or {}
    b_by_store = cand.get("b_by_store") or {}
    for sk in sorted(set(a_by_store) & set(b_by_store)):
        bs = b_by_store[sk]
        if len(bs) != 1:
            continue                     # 같은 가게에 업체가 둘 이상 — 사람 판단으로
        b = bs[0]
        for a in a_by_store[sk]:
            if a["id"] in matched_products:
                continue
            out.append({
                "client_id": b["id"], "client_name": b["name"],
                "tracked_product_id": a["id"], "product_name": a["name"],
                "store_name": a["store"], "product_key": sk,
                "match_method": MATCH_STORE_SLUG,
            })
    return out


def preview_backfill(limit: int = 20) -> Dict[str, Any]:
    """무엇이 연결될지 먼저 보여준다(읽기 전용 — 쓰기 없음)."""
    conn = _get_conn()
    try:
        cand = _collect_candidates(conn)
        pairs = _pairs(cand)
        existing = {
            (r["client_id"], r["tracked_product_id"])
            for r in conn.execute("SELECT client_id, tracked_product_id FROM rank_link")
        }
        new_pairs = [p for p in pairs if (p["client_id"], p["tracked_product_id"]) not in existing]
        return {
            "success": True,
            "axis_a": {"total": cand["a_total"], "with_product_id": cand["a_with_key"]},
            "axis_b": {"total": cand["b_total"], "with_product_id": cand["b_with_key"]},
            "matched_keys": len(set(cand["a_by_key"]) & set(cand["b_by_key"])),
            "pairs_total": len(pairs),
            "already_linked": len(existing),
            "to_insert": len(new_pairs),
            # 규칙별로 나눠 보여준다 — 「상품ID 로 확실히 이은 것」과
            # 「같은 가게라서 이은 것」은 확신 정도가 다르므로 눈으로 갈라 봐야 한다.
            "to_insert_by_product_id": sum(
                1 for p in new_pairs
                if (p.get("match_method") or MATCH_PRODUCT_ID) == MATCH_PRODUCT_ID),
            "to_insert_by_store": sum(
                1 for p in new_pairs if p.get("match_method") == MATCH_STORE_SLUG),
            "samples": new_pairs[:limit],
        }
    except Exception as e:
        logger.error(f"[rank_link] 미리보기 실패: {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()


def apply_backfill(linked_by: int = 0) -> Dict[str, Any]:
    """미리보기와 같은 규칙으로 링크를 적는다.

    멱등 — 이미 있는 조합은 `INSERT OR IGNORE`로 건너뛴다. 기존 순위 데이터는
    읽지도 쓰지도 않는다(링크 행만 늘어난다).
    """
    conn = _get_conn()
    try:
        cand = _collect_candidates(conn)
        pairs = _pairs(cand)
        if not pairs:
            return {"success": True, "inserted": 0, "pairs_total": 0, "linked_total": _count(conn)}
        before = _count(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO rank_link "
            "(client_id, tracked_product_id, product_key, match_method, linked_by) "
            "VALUES (?, ?, ?, ?, ?)",
            # ⚠️ 어느 규칙으로 이었는지 짝마다 남긴다 — 종전엔 전부 product_id 로 박혀
            #    있어, 스토어로 이은 것과 구분이 안 됐다. 나중에 되돌리거나 검수할 때 필요하다.
            [(p["client_id"], p["tracked_product_id"], p["product_key"],
              p.get("match_method") or MATCH_PRODUCT_ID, linked_by)
             for p in pairs],
        )
        conn.commit()
        after = _count(conn)
        logger.info(f"[rank_link] 백필 적용: +{after - before}건 (총 {after})")
        return {"success": True, "inserted": after - before, "pairs_total": len(pairs), "linked_total": after}
    except Exception as e:
        logger.error(f"[rank_link] 백필 실패: {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()


def _count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) n FROM rank_link").fetchone()["n"]


def prune_orphans() -> int:
    """삭제된 업체·상품을 가리키는 링크를 지운다.

    FK CASCADE 를 걸지 않은 이유: 기존 두 테이블의 삭제 경로가 여럿이라
    제약을 새로 걸면 그쪽 삭제가 실패할 위험이 있다. 링크는 부가 정보이므로
    청소로 맞추는 편이 안전하다.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("""
            DELETE FROM rank_link
             WHERE client_id NOT IN (SELECT id FROM clients)
                OR tracked_product_id NOT IN (SELECT id FROM tracked_products)
        """)
        conn.commit()
        n = cur.rowcount or 0
        if n:
            logger.info(f"[rank_link] 고아 링크 {n}건 정리")
        return n
    except Exception as e:
        logger.error(f"[rank_link] 고아 정리 실패: {e}")
        return 0
    finally:
        conn.close()


def run_maintenance(linked_by: int = 0) -> Dict[str, Any]:
    """매일 한 번 — 새로 등록된 것들을 잇고 삭제된 것들을 털어낸다."""
    pruned = prune_orphans()
    res = apply_backfill(linked_by=linked_by)
    res["pruned"] = pruned
    return res


def get_links_for_client(client_id: int) -> List[Dict[str, Any]]:
    """이 업체에 이어진 추적 상품 목록(다음 단계의 조회 통합이 쓸 입구)."""
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT l.tracked_product_id, l.product_key, l.match_method,
                   p.product_name, p.store_name, p.product_url
              FROM rank_link l
              JOIN tracked_products p ON p.id = l.tracked_product_id
             WHERE l.client_id = ?
             ORDER BY l.tracked_product_id
        """, (client_id,))]
    except Exception as e:
        logger.error(f"[rank_link] 업체 {client_id} 링크 조회 실패: {e}")
        return []
    finally:
        conn.close()


def get_links_for_product(tracked_product_id: int) -> List[Dict[str, Any]]:
    """이 추적 상품에 이어진 업체 목록."""
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT l.client_id, l.product_key, l.match_method, c.name AS client_name
              FROM rank_link l
              JOIN clients c ON c.id = l.client_id
             WHERE l.tracked_product_id = ?
             ORDER BY l.client_id
        """, (tracked_product_id,))]
    except Exception as e:
        logger.error(f"[rank_link] 상품 {tracked_product_id} 링크 조회 실패: {e}")
        return []
    finally:
        conn.close()


def link_stats() -> Dict[str, Any]:
    """현황 요약 — 얼마나 이어졌고 얼마가 남았는지."""
    conn = _get_conn()
    try:
        cand = _collect_candidates(conn)
        linked_clients = conn.execute(
            "SELECT COUNT(DISTINCT client_id) n FROM rank_link").fetchone()["n"]
        linked_products = conn.execute(
            "SELECT COUNT(DISTINCT tracked_product_id) n FROM rank_link").fetchone()["n"]
        return {
            "success": True,
            "links": _count(conn),
            "linked_clients": linked_clients,
            "linked_products": linked_products,
            "axis_a_total": cand["a_total"],
            "axis_b_total": cand["b_total"],
            "unlinked_clients": max(0, cand["b_total"] - linked_clients),
            "unlinked_products": max(0, cand["a_total"] - linked_products),
        }
    except Exception as e:
        logger.error(f"[rank_link] 현황 조회 실패: {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()
