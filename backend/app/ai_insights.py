"""AI(Claude) 기반 인사이트 — 자연어 질의 비서 + 텍스트 감성/키워드 분석.

ANTHROPIC_API_KEY 필요. 키 없으면 RuntimeError(상위에서 graceful 처리).
"""
import os
import json
import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


def _call(system: str, user: str, max_tokens: int = 1500) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("AI 키가 아직 설정되지 않았습니다. 관리자(대표)에게 문의하세요.")
    r = requests.post(
        API_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}]},
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"AI 호출 실패 ({r.status_code}): {r.text[:200]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()


def _parse_json(text: str) -> dict:
    if text.startswith("```"):
        text = text.strip("`")
    if "{" not in text or "}" not in text:
        raise RuntimeError("AI 응답 형식 오류(JSON을 찾지 못함)")
    text = text[text.find("{"): text.rfind("}") + 1]
    return json.loads(text)


# ── #8 자연어 질의 비서 ────────────────────────────────────────────────────
ASSISTANT_SYSTEM = """당신은 광고대행사 메타아이앤씨의 데이터 분석 비서다.
사용자의 질문과, 아래 제공되는 '광고주 성과 데이터(JSON)'만 근거로 답한다.

데이터 필드 의미: spend=이번달 광고 소진액(원), ctr=클릭률(%), cpc=클릭당비용(원), roas=광고수익률(%), owner=담당자, status=진행상태.

원칙:
- 데이터에 있는 사실·숫자로만 답한다. 없는 건 "데이터에 없다"고 말한다.
- 한국어로 간결하게. 핵심 결론을 먼저, 그다음 근거 숫자.
- 표가 도움되면 불릿/짧은 목록으로.
- 추측·창작 금지. 광고주는 비전문가이니 쉬운 말로."""


def nl_query(question: str, context: dict) -> str:
    user = (f"[질문]\n{question}\n\n"
            f"[광고주 성과 데이터(JSON)]\n{json.dumps(context, ensure_ascii=False)}")
    return _call(ASSISTANT_SYSTEM, user, max_tokens=1200)


# ── #5 텍스트 감성/키워드 분석 ─────────────────────────────────────────────
TEXT_SYSTEM = """당신은 브랜드 평판 분석가다. 주어진 리뷰/댓글 텍스트를 분석해
아래 JSON으로만 응답한다(다른 텍스트·코드펜스 금지):

{
 "sentiment": {"positive": 0, "neutral": 0, "negative": 0},   // 비율 합 100
 "overall": "한 줄 총평(40자 이내)",
 "keywords_positive": ["자주 나온 긍정 키워드 3~6개"],
 "keywords_negative": ["자주 나온 부정/불만 키워드 0~5개"],
 "ad_copy_ideas": ["리뷰에서 길어올린 광고 카피·키워드 아이디어 2~4개"]
}"""


def analyze_text(texts: list, brand: str = "") -> dict:
    joined = "\n".join(f"- {t}" for t in texts if t)[:6000]
    user = f"브랜드: {brand or '미상'}\n아래는 수집된 리뷰/댓글이다.\n{joined}"
    return _parse_json(_call(TEXT_SYSTEM, user, max_tokens=1200))
