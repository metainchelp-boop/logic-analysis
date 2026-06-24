"""
네이버 쇼핑 SEO 생성기 + 사내 규칙 + 업체 연동 (SEO 최적화 탭 전용)

기능:
- POST /api/seo/generate           : 키워드(+옵션) → Claude로 상품명/태그/카테고리/근거 생성
- GET  /api/seo/rules              : 사내 SEO 규칙 조회 (manager/superadmin)
- PUT  /api/seo/rules              : 사내 SEO 규칙 수정 (superadmin)
- POST /api/seo/save-to-client     : 생성/진단 결과를 업체 기록으로 저장 (manager/superadmin)
- GET  /api/seo/client/{id}/saved  : 업체에 저장된 SEO 작업 목록 (담당자 이어받기)

권한: 광고 관리팀(manager) + 최고관리자(superadmin) 전용.
사내 규칙은 설정 탭에서 superadmin이 편집(코드 재배포 불필요).
"""
import os
import json
import re
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

_claude_client: Optional[anthropic.Anthropic] = None


def _get_claude_client() -> Optional[anthropic.Anthropic]:
    global _claude_client
    if not CLAUDE_API_KEY:
        return None
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    return _claude_client


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


# ============================================================================
# 사내 SEO 규칙 — 기본안(설정 탭에서 수정 가능)
# ============================================================================
DEFAULT_SEO_RULES = """[메타인크 네이버 쇼핑 SEO 작업 기준]

■ 상품명 작성 공식
- 구성 순서: [브랜드] [핵심키워드] [핵심속성1] [핵심속성2] [용량/수량]
- 길이: 25~45자 권장 (네이버 노출 최적 구간)
- 핵심키워드는 앞쪽(브랜드 직후)에 배치
- 같은 단어 2회 이상 반복 금지, 띄어쓰기로 키워드 구분

■ 필수 포함 요소
- 원산지(국내산/수입산 등), 용량·수량, 핵심 용도

■ 금지/지양
- 특수문자·이모지·괄호 남용 금지 (1~2개 이내)
- 과장·최상급 표현 지양 (최고, 1위, 최저가 등)
- 경쟁 브랜드명 사용 금지

■ 태그 작성 기준
- 상품명에 이미 들어간 단어와 중복 최소화
- 검색량 있는 연관/세부(롱테일) 키워드 위주로 10개
- 오타·은어성 키워드는 1~2개까지만

■ 카테고리 선정
- 상위 노출 경쟁 상품들이 가장 많이 속한 카테고리를 우선
- 가능한 소분류까지 구체적으로

■ 작업 순서(체크리스트)
1) 대표 키워드 확정 → 2) 상위 노출 상품 패턴 확인 → 3) 상품명 후보 작성
4) 태그/카테고리 매칭 → 5) 금지어·길이 점검 → 6) 업체 기록 저장/공유"""


def init_seo_db():
    """SEO 규칙 + 업체별 저장 결과 테이블 초기화."""
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seo_rules_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                rules_text TEXT NOT NULL,
                updated_at TEXT,
                updated_by TEXT
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO seo_rules_settings (id, rules_text, updated_at, updated_by) VALUES (1, ?, ?, ?)",
            (DEFAULT_SEO_RULES, datetime.now().isoformat(), "system"),
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_seo_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                keyword TEXT,
                product_name TEXT,
                tags_json TEXT,
                category TEXT,
                rationale_json TEXT,
                source TEXT,
                created_by TEXT,
                created_at TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_seo_results_client "
            "ON client_seo_results(client_id, id DESC)"
        )
        conn.commit()
    except Exception as e:
        logger.error(f"[SEO] init_seo_db 오류: {e}")
    finally:
        conn.close()


def get_seo_rules() -> str:
    conn = _conn()
    try:
        row = conn.execute("SELECT rules_text FROM seo_rules_settings WHERE id = 1").fetchone()
        if row and row["rules_text"]:
            return row["rules_text"]
    except Exception as e:
        logger.warning(f"[SEO] 규칙 조회 실패(기본값 사용): {e}")
    finally:
        conn.close()
    return DEFAULT_SEO_RULES


router = APIRouter(prefix="/api/seo", tags=["seo-generate"])


def require_mgr_team(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """광고 관리팀(manager) + 최고관리자(superadmin) 전용 가드."""
    if current_user.get("role") not in ("manager", "superadmin"):
        raise HTTPException(status_code=403, detail="SEO 최적화는 광고 관리팀 권한자만 사용할 수 있습니다.")
    return current_user


def require_superadmin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SEO 규칙 수정은 최고관리자만 가능합니다.")
    return current_user


# ============================================================================
# 사내 규칙 조회/수정
# ============================================================================
class SeoRulesUpdate(BaseModel):
    rules_text: str


@router.get("/rules")
def read_seo_rules(current_user: dict = Depends(require_mgr_team)):
    return {"success": True, "data": {"rules_text": get_seo_rules()}}


@router.put("/rules")
def write_seo_rules(req: SeoRulesUpdate, current_user: dict = Depends(require_superadmin)):
    text = (req.rules_text or "").strip()
    if not text:
        return {"success": False, "detail": "규칙 내용이 비어 있습니다."}
    if len(text) > 20000:
        return {"success": False, "detail": "규칙이 너무 깁니다 (최대 20,000자)."}
    conn = _conn()
    try:
        conn.execute(
            "UPDATE seo_rules_settings SET rules_text = ?, updated_at = ?, updated_by = ? WHERE id = 1",
            (text, datetime.now().isoformat(), current_user.get("username", "")),
        )
        conn.commit()
        logger.info(f"[SEO] 규칙 수정 by {current_user.get('username')}")
        return {"success": True, "data": {"rules_text": text}}
    except Exception as e:
        logger.error(f"[SEO] 규칙 저장 오류: {e}")
        return {"success": False, "detail": "규칙 저장 중 오류가 발생했습니다."}
    finally:
        conn.close()


# ============================================================================
# SEO 생성
# ============================================================================
class SeoGenerateRequest(BaseModel):
    keyword: str
    category: Optional[str] = ""
    brand: Optional[str] = ""
    features: Optional[str] = ""
    client_id: Optional[int] = None   # 업체 연동(선택)


def _collect_naver_context(keyword: str) -> Dict[str, Any]:
    """네이버 쇼핑 상위 노출 상품에서 실데이터 컨텍스트 수집(best-effort)."""
    ctx: Dict[str, Any] = {"top_titles": [], "categories": [], "price_min": 0, "price_max": 0, "brands": []}
    try:
        from naver_crawler import search_products as _sp
        prods = _sp(keyword, max_results=40) or []
    except Exception as e:
        logger.warning(f"[SEO생성] 네이버 컨텍스트 수집 실패(스킵): {e}")
        return ctx

    titles, cats, prices, brands = [], [], [], []
    for p in prods[:40]:
        nm = (p.get("product_name") or "").strip()
        if nm:
            titles.append(nm)
        c1 = (p.get("category1") or "").strip()
        c2 = (p.get("category2") or "").strip()
        cat = " > ".join([c for c in (c1, c2) if c])
        if cat:
            cats.append(cat)
        pr = p.get("price", 0) or 0
        if isinstance(pr, (int, float)) and pr > 0:
            prices.append(int(pr))
        br = (p.get("brand") or "").strip()
        if br:
            brands.append(br)

    cat_freq: Dict[str, int] = {}
    for c in cats:
        cat_freq[c] = cat_freq.get(c, 0) + 1
    top_cats = sorted(cat_freq.items(), key=lambda x: -x[1])[:3]

    ctx["top_titles"] = titles[:20]
    ctx["categories"] = [c for c, _ in top_cats]
    if prices:
        ctx["price_min"] = min(prices)
        ctx["price_max"] = max(prices)
    return ctx


def _build_prompt(req: SeoGenerateRequest, ctx: Dict[str, Any], rules: str) -> str:
    lines = [
        "당신은 네이버 스마트스토어/쇼핑 SEO 전문가입니다.",
        "아래 '사내 작업 기준'을 반드시 우선 준수하여, 네이버 쇼핑 검색 노출에 최적화된 결과를 만들어 주세요.",
        "",
        "===== 사내 작업 기준(반드시 준수) =====",
        rules.strip(),
        "===== 기준 끝 =====",
        "",
        f"[대표 키워드] {req.keyword}",
    ]
    if req.brand:
        lines.append(f"[브랜드] {req.brand}")
    if req.category:
        lines.append(f"[희망 카테고리] {req.category}")
    if req.features:
        lines.append(f"[제품 특징/속성] {req.features}")

    if ctx.get("top_titles"):
        lines.append("")
        lines.append("[현재 네이버 상위 노출 상품명 예시 — 참고용, 그대로 베끼지 말 것]")
        for t in ctx["top_titles"][:15]:
            lines.append(f"- {t}")
    if ctx.get("categories"):
        lines.append("")
        lines.append("[상위 상품 주요 카테고리]")
        for c in ctx["categories"]:
            lines.append(f"- {c}")
    if ctx.get("price_min") and ctx.get("price_max"):
        lines.append(f"[상위 상품 가격대] {ctx['price_min']:,}원 ~ {ctx['price_max']:,}원")

    lines += [
        "",
        "반드시 아래 JSON 형식 '하나만' 출력하세요. 다른 설명/마크다운/코드펜스 없이 순수 JSON만.",
        "각 근거(rationale)에는 위 '사내 작업 기준'의 어떤 항목을 따랐는지 드러나게 작성하세요.",
        "{",
        '  "product_names": ["후보1", "후보2", "후보3"],',
        '  "tags": ["태그1", "태그2", "... 총 10개"],',
        '  "category": "대분류 > 중분류 > 소분류",',
        '  "rationale": ["근거1", "근거2", "근거3", "근거4"]',
        "}",
    ]
    return "\n".join(lines)


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            return None
    return None


@router.post("/generate")
def seo_generate(req: SeoGenerateRequest, current_user: dict = Depends(require_mgr_team)):
    """네이버 쇼핑 SEO 상품명/태그/카테고리 생성 (사내 규칙 적용, 관리팀 전용)."""
    keyword = (req.keyword or "").strip()
    if not keyword:
        return {"success": False, "detail": "키워드를 입력해주세요."}
    if len(keyword) > 100:
        return {"success": False, "detail": "키워드가 너무 깁니다."}

    client = _get_claude_client()
    if not client:
        return {"success": False, "detail": "AI 생성 기능을 사용하려면 관리자가 CLAUDE_API_KEY를 설정해야 합니다."}

    ctx = _collect_naver_context(keyword)
    rules = get_seo_rules()
    prompt = _build_prompt(req, ctx, rules)

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else ""
        logger.info(f"[SEO생성] '{keyword}' by {current_user.get('username')} "
                    f"(tokens in={getattr(resp.usage,'input_tokens','?')}, out={getattr(resp.usage,'output_tokens','?')})")
    except anthropic.APITimeoutError:
        return {"success": False, "detail": "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."}
    except Exception as e:
        logger.error(f"[SEO생성] Claude 호출 오류: {e}")
        return {"success": False, "detail": "SEO 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}

    parsed = _parse_json(raw)
    if not parsed:
        logger.warning(f"[SEO생성] JSON 파싱 실패: {raw[:200]}")
        return {"success": False, "detail": "AI 응답을 해석하지 못했습니다. 다시 시도해주세요."}

    names = [str(x).strip() for x in (parsed.get("product_names") or []) if str(x).strip()][:5]
    tags = [str(x).strip().lstrip("#") for x in (parsed.get("tags") or []) if str(x).strip()][:10]
    category = str(parsed.get("category") or "").strip()
    rationale = [str(x).strip() for x in (parsed.get("rationale") or []) if str(x).strip()][:8]

    if not names:
        return {"success": False, "detail": "상품명 생성에 실패했습니다. 다시 시도해주세요."}

    return {
        "success": True,
        "data": {
            "keyword": keyword,
            "product_names": names,
            "tags": tags,
            "category": category,
            "rationale": rationale,
            "context": {
                "sampled_titles": len(ctx.get("top_titles") or []),
                "categories": ctx.get("categories") or [],
                "price_min": ctx.get("price_min") or 0,
                "price_max": ctx.get("price_max") or 0,
            },
        },
    }


# ============================================================================
# 업체 연동 — 결과 저장 / 조회
# ============================================================================
class SaveSeoToClientRequest(BaseModel):
    client_id: int
    keyword: str
    product_name: Optional[str] = ""
    tags: Optional[List[str]] = None
    category: Optional[str] = ""
    rationale: Optional[List[str]] = None
    source: Optional[str] = "generate"   # generate | diagnose


def _client_belongs(conn, client_id: int, current_user: dict) -> bool:
    """superadmin은 전체, manager는 본인 등록 업체만 저장 허용."""
    if current_user.get("role") == "superadmin":
        row = conn.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone()
        return row is not None
    row = conn.execute(
        "SELECT 1 FROM clients WHERE id = ? AND (created_by = ? OR created_by IS NULL OR created_by = '')",
        (client_id, current_user["id"]),
    ).fetchone()
    return row is not None


@router.post("/save-to-client")
def save_seo_to_client(req: SaveSeoToClientRequest, current_user: dict = Depends(require_mgr_team)):
    conn = _conn()
    try:
        if not _client_belongs(conn, req.client_id, current_user):
            raise HTTPException(status_code=403, detail="해당 업체에 저장할 권한이 없습니다.")
        conn.execute(
            """INSERT INTO client_seo_results
               (client_id, keyword, product_name, tags_json, category, rationale_json, source, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                req.client_id,
                (req.keyword or "").strip(),
                (req.product_name or "").strip(),
                json.dumps(req.tags or [], ensure_ascii=False),
                (req.category or "").strip(),
                json.dumps(req.rationale or [], ensure_ascii=False),
                req.source or "generate",
                current_user.get("username", ""),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        logger.info(f"[SEO] 업체#{req.client_id} 저장 by {current_user.get('username')}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SEO] save-to-client 오류: {e}")
        return {"success": False, "detail": "업체 저장 중 오류가 발생했습니다."}
    finally:
        conn.close()


@router.get("/client/{client_id}/saved")
def list_client_seo(client_id: int, current_user: dict = Depends(require_mgr_team)):
    conn = _conn()
    try:
        if not _client_belongs(conn, client_id, current_user):
            raise HTTPException(status_code=403, detail="해당 업체 조회 권한이 없습니다.")
        rows = conn.execute(
            """SELECT id, keyword, product_name, tags_json, category, rationale_json, source, created_by, created_at
               FROM client_seo_results WHERE client_id = ? ORDER BY id DESC LIMIT 20""",
            (client_id,),
        ).fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "keyword": r["keyword"],
                "product_name": r["product_name"],
                "tags": json.loads(r["tags_json"] or "[]"),
                "category": r["category"],
                "rationale": json.loads(r["rationale_json"] or "[]"),
                "source": r["source"],
                "created_by": r["created_by"],
                "created_at": r["created_at"],
            })
        return {"success": True, "data": items}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SEO] list_client_seo 오류: {e}")
        return {"success": False, "data": [], "detail": "조회 중 오류가 발생했습니다."}
    finally:
        conn.close()
