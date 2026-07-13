"""AI 결과보고서 생성 — Claude API.

대표 확정 양식(2026-06-12):
  보고서는 항상 기간 지정 생성. 피드백은 반드시 4단계 —
  ① 현재 진단 ② 개선 방향 ③ 방향성 수립 ④ 전략 제안.
"""
import os
import json
import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM = """당신은 광고대행사 메타아이앤씨의 시니어 마케팅 컨설턴트다.
광고주에게 보내는 월간/기간 결과보고서의 코멘트를 작성한다.

입력 데이터는 연동된 매체별로 들어온다(네이버 검색광고, 메타체험단 체험단 캠페인,
그 밖에 추후 추가되는 매체 등). 들어온 매체를 모두 종합해 하나의 보고서로 작성한다.

원칙:
- 두괄식. 숫자에 근거해서만 말한다(데이터에 없는 수치 창작 금지).
- 여러 매체가 있으면 매체별 성과를 비교·연결해 통합적으로 해석한다(어느 매체가 효율적인지 등).
- 광고 지표가 0이거나 비어 있으면 "미집행/저노출 상태"로 진단하고 집행 재개·세팅 점검을 제안한다.
- 체험단(리뷰 캠페인) 데이터는 모집/신청/선정/리뷰등록 펀널과 리뷰 이행률, 유입매체로 해석한다.
- 전문용어는 쉬운 말로 풀어 쓴다(광고주는 비전문가).
- 반드시 아래 JSON 형식으로만 응답한다(다른 텍스트·코드펜스 금지):

{
 "conclusion": "한 줄 결론(두괄식, 80자 이내)",
 "kpi_comment": "핵심 숫자 해석 2~3문장",
 "feedback": {
   "diagnosis":   ["현재 진단 — 데이터 기반 현황·문제점, 불릿 2~4개"],
   "improvement": ["개선 방향 — 진단된 문제의 구체적 개선 포인트, 불릿 2~4개"],
   "direction":   ["방향성 수립 — 다음 기간 운영 방향·우선순위, 불릿 2~3개"],
   "strategy":    ["전략 제안 — 실행 가능한 전략(예산·채널믹스·키워드·소재), 불릿 2~4개"]
 }
}"""


def generate(client_name: str, category: str, date_from: str, date_to: str, perf: dict) -> dict:
    """기간 성과 데이터로 보고서 코멘트 생성. ANTHROPIC_API_KEY 필요."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("AI 키가 아직 설정되지 않았습니다. 관리자(대표)에게 문의하세요.")

    user_msg = (
        f"광고주: {client_name} (업종: {category or '미상'})\n"
        f"보고 기간: {date_from} ~ {date_to}\n"
        f"아래는 연동된 매체별 성과 데이터(JSON)다. 매체 키별로 데이터를 종합해 보고서를 작성하라.\n"
        f"{json.dumps(perf, ensure_ascii=False)}"
    )
    r = requests.post(
        API_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 2500,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"AI 호출 실패 ({r.status_code}): {r.text[:300]}")
    text = "".join(
        b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"
    ).strip()
    # 혹시 코드펜스가 붙으면 제거
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    if "}" in text:
        text = text[: text.rfind("}") + 1]
    return json.loads(text)
