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


GRACE_DAYS = 2          # 등록 후 이 날짜가 지나도 주인을 못 찾으면 비활성으로 내린다


def disable_ownerless() -> Dict[str, Any]:
    """주인을 못 찾은 추적 상품을 추적 대상에서 내린다(대표 확정 2026-08-28).

    ⚠️ 지우지 않는다 — `disabled_at` 표시만 붙인다. 지워 버리면 그 상품에 달린
       키워드·지금까지 쌓인 순위가 함께 사라져 되돌릴 수 없다. 표시만 붙이면
       나중에 주인이 밝혀졌을 때 그 칸을 비우는 것으로 그대로 되살아난다.

    ⚠️ 등록 직후는 건드리지 않는다(GRACE_DAYS). 직원이 방금 등록한 상품은
       아직 연결이 안 맺어진 게 정상이고, 그걸 그 자리에서 내리면
       「등록했는데 추적이 안 된다」가 된다.

    ⚠️ 반드시 apply_backfill() **뒤에** 부를 것 — 앞에서 부르면 오늘 이어질 수
       있었던 상품까지 내려간다.
    """
    # ⚠️ 2026-08-29 실사고: 여기서 존재하지 않는 _conn() 을 불러 NameError 가 났고,
    #    run_maintenance 전체가 넘어지면서 01:20 의 큐 2차 정리까지 함께 건너뛰었다
    #    (첫 실행 로그: 「순위 축 브리지 갱신 예외: name '_conn' is not defined」).
    #    이 파일의 연결 헬퍼는 _get_conn 이다. conn 획득도 try 안으로 — 어떤 실패도
    #    호출자를 넘어뜨리지 않는다(부가 기능이 본 기능을 죽이면 안 된다).
    conn = None
    try:
        conn = _get_conn()
        from tracking_eligibility import ensure_disabled_column
        ensure_disabled_column(conn)
        rows = conn.execute(
            "SELECT p.id, p.product_name, p.store_name FROM tracked_products p "
            " WHERE COALESCE(p.disabled_at,'') = '' "
            "   AND p.id NOT IN (SELECT tracked_product_id FROM rank_link) "
            "   AND date(COALESCE(p.created_at, '2000-01-01')) "
            "       <= date('now','localtime',?)",
            (f"-{GRACE_DAYS} day",)).fetchall()
        ids = [r[0] for r in rows]
        if ids:
            conn.executemany(
                "UPDATE tracked_products SET disabled_at = datetime('now','localtime') "
                " WHERE id = ? AND COALESCE(disabled_at,'') = ''",
                [(i,) for i in ids])
            conn.commit()
            for r in rows[:20]:
                logger.info(f"[rank_link] 주인 없어 추적 중지: #{r[0]} {r[1] or ''} ({r[2] or '가게명 없음'})")
        return {"disabled": len(ids)}
    except Exception as e:
        logger.warning(f"[rank_link] 주인 없는 상품 정리 실패(무시): {e}")
        return {"disabled": 0}
    finally:
        if conn is not None:
            conn.close()


def run_maintenance(linked_by: int = 0) -> Dict[str, Any]:
    """매일 한 번 — 새로 등록된 것들을 잇고, 삭제된 것들을 털고,
       그래도 주인을 못 찾은 것은 추적에서 내린다."""
    pruned = prune_orphans()
    res = apply_backfill(linked_by=linked_by)
    res["pruned"] = pruned
    res["disabled"] = disable_ownerless().get("disabled", 0)
    return res


def share_targets(link_map, client_keyword_map, tracked_product_id, keyword):
    """이 상품·이 키워드로 잰 값을 「어느 업체에 나눠 적을지」 고르는 규칙(순수 함수).

    대표 지시(2026-08-27) 「순위 추적 1번만 진행하고 필요한 곳에 보내주기」의 판정부다.
    순위는 08:00 배치가 키워드당 한 번만 잰다(유니버스가 키워드 합집합이라 원래 그렇다).
    나뉘어 있던 건 「기록하는 자리」다 —
      축A 쇼핑 순위 추적 화면 = rankings            (tracked_products 에 등록한 것만 보인다)
      축B 로직 분석 업체 화면 = client_rank_history (clients.main_keywords 에 있는 것만 보인다)
    이 표가 이미 「이 추적 상품 = 이 업체」를 알고 있으니, 잰 값을 그 짝에도 적어 주면
    화면 둘이 같은 것을 보게 된다. 합치지 않는다 — 나눠 준다.

    · link_map            {추적상품 id: [업체 id, ...]} — 자격 통과한 업체만 담겨 있다
    · client_keyword_map  {업체 id: [그 업체가 자기 대표 상품으로 재는 키워드, ...]}

    ⚠️ 배치 루프 안에 두지 않고 여기 둔 이유는 두 가지다.
       ① 루프 안에서는 검사할 수가 없다 — 규칙이 두 곳으로 갈리면 화면에 보이는 것과
          실제 적히는 것이 어긋난다.
       ② 이 표(rank_link)가 「이 상품이 어느 업체 것인가」의 주인이므로, 그 답을 쓰는
          규칙도 같은 자리에 있는 편이 다음 사람이 찾기 쉽다.

    ⚠️ 그 업체가 이 키워드를 이미 자기 대표 상품으로 재고 있으면 뺀다.
       업체 대표 상품 기준 순위가 우선이고, 덮어쓰면 종전 화면이 바뀐다(무회귀).
    """
    out = []
    for cid in link_map.get(tracked_product_id, []):
        if keyword in (client_keyword_map.get(cid) or []):
            continue
        out.append(cid)
    return out


def link_on_register(tracked_product_id: int, client_id: Optional[int],
                     linked_by: int = 0) -> Dict[str, Any]:
    """추적 상품을 등록하는 그 자리에서 업체와 이어 둔다 (2026-08-27 대표 지시).

    ⚠️ 왜 등록 시점인가 — 종전엔 이을 기회가 매일 01:20 정기 갱신뿐이었고,
       그 갱신은 상품번호·가게 이름이 맞아떨어질 때만 잇는다. 그래서 업체 주소와
       다른 상품을 등록하면 **영영 주인이 없는 채로** 남았다(실측 126개).
       등록하는 사람은 그 상품이 누구 것인지 알고 있으므로, 그때 받아 두는 게
       가장 확실하고 되돌릴 일도 없다.

    · client_id 를 주면 그것으로 잇는다(사람이 고른 것이라 `manual` 로 남긴다).
    · 안 주면 정기 갱신과 **같은 규칙**으로 자동 매칭을 시도한다 —
      여기서 규칙을 새로 만들면 등록으로 이은 것과 배치로 이은 것이 갈린다.
    · 둘 다 실패해도 **등록 자체를 막지 않는다.** 옛 화면이 이 값을 안 보내는데
      서버가 거절하면 등록이 통째로 멈춘다. 대신 못 이었다는 사실을 돌려준다.

    반환: {"linked": bool, "client_id": int|None, "method": str|None, "reason": str}
    """
    conn = _get_conn()
    try:
        if client_id:
            row = conn.execute(
                "SELECT id, name FROM clients WHERE id = ? AND status='active'", (client_id,)
            ).fetchone()
            if not row:
                return {"linked": False, "client_id": None, "method": None,
                        "reason": "고른 업체를 찾을 수 없습니다(삭제됐거나 중지된 업체)."}
            conn.execute(
                "INSERT OR IGNORE INTO rank_link "
                "(client_id, tracked_product_id, product_key, match_method, linked_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["id"], tracked_product_id, "", MATCH_MANUAL, linked_by),
            )
            conn.commit()
            return {"linked": True, "client_id": row["id"], "method": MATCH_MANUAL,
                    "reason": f"{row['name']} 업체로 이었습니다."}

        # 업체를 안 골랐으면 정기 갱신과 같은 규칙으로 시도
        pairs = [p for p in _pairs(_collect_candidates(conn))
                 if p["tracked_product_id"] == tracked_product_id]
        if len(pairs) == 1:
            p = pairs[0]
            conn.execute(
                "INSERT OR IGNORE INTO rank_link "
                "(client_id, tracked_product_id, product_key, match_method, linked_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (p["client_id"], tracked_product_id, p["product_key"],
                 p.get("match_method") or MATCH_PRODUCT_ID, linked_by),
            )
            conn.commit()
            return {"linked": True, "client_id": p["client_id"],
                    "method": p.get("match_method") or MATCH_PRODUCT_ID,
                    "reason": f"{p['client_name']} 업체로 자동으로 이었습니다."}
        if len(pairs) > 1:
            return {"linked": False, "client_id": None, "method": None,
                    "reason": "같은 가게에 업체가 여럿이라 자동으로 못 정합니다. 업체를 골라 주세요."}
        return {"linked": False, "client_id": None, "method": None,
                "reason": "이 상품과 이어질 업체를 못 찾았습니다. 업체를 골라 주세요."}
    except Exception as e:
        logger.error(f"[rank_link] 등록 시 연결 실패: {e}")
        return {"linked": False, "client_id": None, "method": None,
                "reason": "연결 처리 중 문제가 생겼습니다."}
    finally:
        conn.close()


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
