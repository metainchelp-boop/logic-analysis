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


# ── 네이버 검색광고 AI 진단 ───────────────────────────────────────────────
DIAGNOSE_SYSTEM = """당신은 네이버 검색광고를 운영하는 광고대행사의 베테랑 마케터다.
주어진 캠페인·광고그룹·키워드 성과 데이터를 읽고 원인을 진단한다.

원칙:
- 데이터에 있는 숫자로만 말한다. 없는 건 단정하지 않는다.
- 광고주가 아니라 **담당 마케터**에게 말한다. 실무 용어는 써도 되지만 결론이 먼저다.
- 소진이 큰데 성과가 없는 구간을 최우선으로 짚는다(돈이 새는 곳).
- 담당자 메모가 있으면 반드시 반영한다(예: "리뉴얼 전이라 보수 운영" → 확장 제안 자제).

아래 JSON 으로만 응답한다(코드펜스 금지):
{
 "headline": "한 줄 결론(40자 이내)",
 "problem": "핵심 문제와 원인 — 캠페인·키워드 이름과 숫자를 넣어 2~3문장",
 "good": "잘 되고 있는 것 — 이름과 숫자를 넣어 1~2문장",
 "advice": "권고 방향 1~2문장(구체 실행안은 별도로 생성되니 방향만)",
 "severity": "high | mid | low"
}"""


def diagnose_searchad(payload: dict) -> dict:
    user = ("[광고주·성과 데이터(JSON)]\n" + json.dumps(payload, ensure_ascii=False))
    return _parse_json(_call(DIAGNOSE_SYSTEM, user, max_tokens=1400))


# ── 네이버 검색광고 AI 세팅 제안 ──────────────────────────────────────────
SETUP_SYSTEM = """당신은 네이버 검색광고 운영 전문가다. 성과 데이터를 보고
**담당자가 검토·승인할 변경안**을 만든다. 당신이 직접 집행하는 것이 아니다.

만들 수 있는 변경은 4가지뿐이다:
- "bid"      : 키워드 입찰가 변경    (target_id = keyword_id 필수)
- "kw_off"   : 키워드 중지          (target_id = keyword_id 필수)
- "kw_add"   : 키워드 추가          (adgroup_id 필수, target_id 없음)
- "budget"   : 광고그룹 일예산 변경  (target_id = adgroup_id 필수)

규칙:
- **입찰가·예산 변경은 현재값 대비 ±50% 를 넘지 않게** 제안한다(넘으면 시스템이 자동으로 잘라낸다).
- 소진이 0 이거나 데이터가 없는 대상은 건드리지 않는다.
- 근거(why)에는 **숫자를 반드시 넣는다**(소진액·ROAS·클릭·전환).
- 담당자 메모가 보수적 운영을 요구하면 확장(입찰 인상·키워드 추가)은 checked=false 로 둔다.
- 제안은 최대 8개. 확실한 것부터.
- checked: 담당자가 바로 적용해도 안전하다고 판단되면 true, 검토가 필요하면 false.

아래 JSON 으로만 응답한다(코드펜스 금지):
{
 "summary": "제안 전체 요약 한 줄",
 "items": [
   {"type":"bid|kw_off|kw_add|budget",
    "target_id":"대상 ID(kw_add 는 빈 문자열)",
    "adgroup_id":"kw_add 일 때 필수, 그 외 빈 문자열",
    "label":"사람이 읽는 대상 이름(예: 키워드 '굴비선물세트')",
    "current":"현재 상태(예: 1200원 / 운영중)",
    "proposed":"제안 상태(예: 700원 / 중지)",
    "proposed_value": 700,
    "keyword":"kw_add 일 때 추가할 검색어, 그 외 빈 문자열",
    "why":"근거 — 숫자 포함 1~2문장",
    "checked": true}
 ]
}"""


def propose_searchad_setup(payload: dict) -> dict:
    user = ("[광고주·성과 데이터(JSON)]\n" + json.dumps(payload, ensure_ascii=False))
    return _parse_json(_call(SETUP_SYSTEM, user, max_tokens=2600))
