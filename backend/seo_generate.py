"""
네이버 쇼핑 SEO 생성기 (SEO 최적화 탭 전용)

키워드(+ 선택: 카테고리/브랜드/제품특징)를 입력받아 Claude로
- 최적화된 상품명 후보
- 추천 검색태그
- 추천 카테고리 경로
- 적용 근거 체크리스트
를 생성한다.

권한: 광고 관리팀(manager) + 최고관리자(superadmin) 전용.
(auth.require_register_permission 과 동일한 기준 — 일반 admin/viewer 제외)
"""
import os
import json
import re
import logging
from typing import Optional, List, Dict, Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user

logger = logging.getLogger(__name__)

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


router = APIRouter(prefix="/api/seo", tags=["seo-generate"])


def require_mgr_team(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """광고 관리팀(manager) + 최고관리자(superadmin) 전용 가드."""
    if current_user.get("role") not in ("manager", "superadmin"):
        raise HTTPException(status_code=403, detail="SEO 최적화는 광고 관리팀 권한자만 사용할 수 있습니다.")
    return current_user


class SeoGenerateRequest(BaseModel):
    keyword: str
    category: Optional[str] = ""      # 선택: 카테고리 힌트
    brand: Optional[str] = ""         # 선택: 브랜드명
    features: Optional[str] = ""      # 선택: 제품 특징/속성 (자유 텍스트)


def _collect_naver_context(keyword: str) -> Dict[str, Any]:
    """네이버 쇼핑 상위 노출 상품에서 실데이터 컨텍스트 수집(best-effort).
    429/네트워크 실패 시 빈 컨텍스트 반환 — 생성은 계속 진행."""
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

    # 카테고리 빈도순 상위 3
    cat_freq: Dict[str, int] = {}
    for c in cats:
        cat_freq[c] = cat_freq.get(c, 0) + 1
    top_cats = sorted(cat_freq.items(), key=lambda x: -x[1])[:3]

    brand_freq: Dict[str, int] = {}
    for b in brands:
        brand_freq[b] = brand_freq.get(b, 0) + 1
    top_brands = [b for b, _ in sorted(brand_freq.items(), key=lambda x: -x[1])[:8]]

    ctx["top_titles"] = titles[:20]
    ctx["categories"] = [c for c, _ in top_cats]
    ctx["brands"] = top_brands
    if prices:
        ctx["price_min"] = min(prices)
        ctx["price_max"] = max(prices)
    return ctx


def _build_prompt(req: SeoGenerateRequest, ctx: Dict[str, Any]) -> str:
    lines = [
        "당신은 네이버 스마트스토어/쇼핑 SEO 전문가입니다.",
        "아래 정보를 바탕으로 네이버 쇼핑 검색 노출에 최적화된 결과를 만들어 주세요.",
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
        "네이버 쇼핑 SEO 규칙을 반드시 지키세요:",
        "1) 상품명: 핵심키워드를 앞쪽에 배치, 25~45자 권장, 특수문자/이모지/중복단어 금지, 브랜드+핵심키워드+주요속성 순.",
        "2) 태그: 검색 가능성 높은 연관/세부 키워드 위주, 상품명과 중복되지 않는 보조 키워드 포함, 10개.",
        "3) 카테고리: 네이버 쇼핑 카테고리 경로 형태('대분류 > 중분류 > 소분류')로 1개 추천.",
        "4) 근거: 각 제안이 왜 노출에 유리한지 한 줄씩 설명.",
        "",
        "반드시 아래 JSON 형식 '하나만' 출력하세요. 다른 설명/마크다운/코드펜스 없이 순수 JSON만.",
        "{",
        '  "product_names": ["후보1", "후보2", "후보3"],',
        '  "tags": ["태그1", "태그2", "... 총 10개"],',
        '  "category": "대분류 > 중분류 > 소분류",',
        '  "rationale": ["근거1", "근거2", "근거3", "근거4"]',
        "}",
    ]
    return "\n".join(lines)


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Claude 응답에서 JSON 객체 추출(코드펜스/잡텍스트 방어)."""
    if not text:
        return None
    t = text.strip()
    # 코드펜스 제거
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # 본문에서 첫 { ~ 마지막 } 구간 추출
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            return None
    return None


@router.post("/generate")
def seo_generate(req: SeoGenerateRequest, current_user: dict = Depends(require_mgr_team)):
    """네이버 쇼핑 SEO 상품명/태그/카테고리 생성 (관리팀 전용)."""
    keyword = (req.keyword or "").strip()
    if not keyword:
        return {"success": False, "detail": "키워드를 입력해주세요."}
    if len(keyword) > 100:
        return {"success": False, "detail": "키워드가 너무 깁니다."}

    client = _get_claude_client()
    if not client:
        return {"success": False, "detail": "AI 생성 기능을 사용하려면 관리자가 CLAUDE_API_KEY를 설정해야 합니다."}

    ctx = _collect_naver_context(keyword)
    prompt = _build_prompt(req, ctx)

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

    # 정규화/방어
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
