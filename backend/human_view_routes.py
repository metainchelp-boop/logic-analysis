"""관리팀 순위 읽기 도우미 — 경로 (규칙은 human_view.py · 2026-09-24)

  GET  /api/human-view/todo    할 일 목록(확장)          — X-Human-Token · X-Human-Pc
  POST /api/human-view/page    사람이 넘긴 화면 한 건(확장) — X-Human-Token · X-Human-Pc
  GET  /api/human-view/token   설치용 토큰(최고관리자)     — 로그인
  GET  /api/human-view/stats   운영 화면(PC 번호별)        — 로그인

⚠️ 서버는 네이버를 부르지 않는다. 받은 화면으로 순위를 적을 뿐이다.
⚠️ 추적 키워드가 아니면 아무것도 저장하지 않는다(accepted:false) — 직원 검색 기록을 남기지 않는다.
"""
import json
import logging
import os
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from auth import get_current_user
import human_view as hv

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/human-view", tags=["human-view"])

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


def _collector_token() -> str:
    return os.getenv("COLLECTOR_TOKEN", "")


def _auth(token, pc) -> int:
    if not _collector_token():
        raise HTTPException(status_code=503, detail="서버에 토큰이 설정되지 않았습니다.")
    if not hv.token_ok(token, _collector_token()):
        raise HTTPException(status_code=401, detail="도우미 인증 실패 — 팝업의 연결 코드를 확인하세요.")
    try:
        return hv.pc_no(pc)
    except hv.HumanViewError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _universe_and_done(conn, today):
    """수집기와 **같은 함수**로 유니버스·완료를 구한다(규칙을 새로 쓰지 않는다)."""
    import collector as C
    uni = C._keyword_universe(conn)
    done = {r[0] for r in conn.execute(
        "SELECT keyword FROM collected_serp WHERE collected_date = ?", (today,)).fetchall()}
    try:
        from collector_observation import found_done_keywords
        done |= found_done_keywords(conn, today)
    except Exception:
        pass
    return uni, done


@router.get("/todo")
def human_todo(x_human_token: str = Header(None), x_human_pc: str = Header(None)):
    pc = _auth(x_human_token, x_human_pc)
    import collector as C
    today = C._effective_date()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        hv.init_db(conn)
        hv.purge_old(conn)                     # 보관 30일 — 하루 수십 줄이라 여기서 지워도 가볍다
        uni, done = _universe_and_done(conn, today)
        try:
            from collector_observation import attempted_map
            attempted = attempted_map(conn, today)
        except Exception:
            attempted = {}
        return {"success": True, **hv.todo(conn, uni, today, done, attempted, pc)}
    finally:
        conn.close()


@router.post("/page")
async def human_page(request: Request, x_human_token: str = Header(None), x_human_pc: str = Header(None)):
    pc = _auth(x_human_token, x_human_pc)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="본문을 읽지 못했습니다.")
    try:
        item = hv.validate(body)
    except hv.HumanViewError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    import collector as C
    today = C._effective_date()
    kw = item["keyword"]
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        uni = C._keyword_universe(conn)
        if kw not in uni:
            # 추적 키워드가 아니다 — 아무것도 남기지 않는다(로그에도 검색어를 안 찍는다).
            return {"success": True, "accepted": False, "reason": "not-tracked"}
        normalized = [C._normalize_collected(p) for p in item["products"]]

        def _record(positive_only: bool):
            try:
                from rank_record import record_ranks_for_keyword
                return record_ranks_for_keyword(kw, normalized, positive_only=positive_only)
            except Exception as e:
                logger.warning(f"[human-view] 순위 기록 실패(pc{pc}): {e}")
                return {}

        def _store_full():
            meta = {"source": "human", "pc": pc, "pagesRead": item["pages"], "loggedIn": item["loggedIn"],
                    "endOfResults": item["end"], "collectorVersion": "human-" + item["extVersion"]}
            products = [{k: p.get(k, "") for k in ("rank", "productId", "nvMid", "title", "link", "price", "mallName",
                                                    "brand", "category1", "category2", "category3", "reviewCount")}
                        for p in item["products"]]
            c2 = sqlite3.connect(DB_PATH, timeout=10)
            try:
                c2.execute("""
                    INSERT INTO collected_serp (keyword, collected_date, total, products_json, product_count, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(keyword, collected_date) DO UPDATE SET
                        total=excluded.total, products_json=excluded.products_json,
                        product_count=excluded.product_count, meta_json=excluded.meta_json,
                        created_at=datetime('now','localtime')
                """, (kw, today, int(body.get("total") or 0), json.dumps(products, ensure_ascii=False),
                      len(products), json.dumps(meta, ensure_ascii=False)))
                c2.execute("UPDATE collect_requests SET status='done' WHERE keyword=?", (kw,))
                c2.commit()
            finally:
                c2.close()

        try:
            from collector_observation import init_observation_db
            init_observation_db(conn)          # 「대상 다 찾음」 표(collector_found_done)가 없을 수 있다
        except Exception:
            pass
        result = hv.ingest(conn, item, today, pc, _record, _store_full)
        r = result.get("ranked") or {}
        # ⚠️ 공개 저장소의 진단 런 로그에 로그 꼬리가 찍힌다 — 검색어는 싣지 않는다.
        logger.info(f"[human-view] pc{pc} {result['status']} · {item['covered']}위까지 · "
                    f"대상 {r.get('targets_found', 0)}/{r.get('targets_total', 0)} · 로그인 {item['loggedIn']}")
        return result
    finally:
        conn.close()


@router.get("/token")
def human_token(current_user: dict = Depends(get_current_user)):
    """설치용 연결 코드 — 최고관리자만. 관리팀 PC 에는 수집기 토큰이 아니라 이 값을 넣는다."""
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="최고관리자만 볼 수 있습니다.")
    t = hv.derive_token(_collector_token())
    if not t:
        raise HTTPException(status_code=503, detail="서버에 토큰이 설정되지 않았습니다.")
    return {"success": True, "token": t}


@router.get("/stats")
def human_stats(current_user: dict = Depends(get_current_user)):
    import collector as C
    today = C._effective_date()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        hv.init_db(conn)
        out = hv.stats(conn, today)
        out["loginCompare"] = hv.login_compare(conn, (date.today() - timedelta(days=7)).isoformat())
        return {"success": True, "date": today, **out}
    finally:
        conn.close()
