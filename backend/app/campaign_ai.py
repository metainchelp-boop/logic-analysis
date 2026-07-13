"""AI 캠페인 제안 생성 — 실제 광고주 데이터로 다음 기간 캠페인안 설계(Claude API).

이 모듈은 '제안만' 만든다. 실제 광고 플랫폼 세팅(쓰기)은 하지 않는다 —
실제 적용은 adapters/naver_searchad.apply_plan + 라우터의 승인·실행 단계에서 처리.
"""
import os
import json
import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM = """당신은 광고대행사 메타아이앤씨의 퍼포먼스 광고 설계 전문가다.
광고주의 '실제 성과 데이터'와 '목표·월 예산'을 받아, 다음 기간에 실행할 구체적 캠페인안을 설계한다.

원칙:
- 데이터에 근거한다. 데이터에 없는 수치를 창작하지 않는다.
  성과 데이터가 비어 있거나 미집행이면, 업종 일반 기준으로 '보수적으로' 잡고 그 가정을 notes에 명시한다.
- ★사용자가 '진행할 매체'를 지정한다. channel_mix는 '지정된 매체로만' 구성한다.
  지정되지 않은 매체는 channel_mix에 절대 포함하지 않는다. pct 합은 100, 예산 합은 월 예산 이내.
- 네이버 검색광고가 '지정 매체'에 포함된 경우에만 naver_searchad 블록을 '실제로 생성 가능한' 형태로 채운다:
  캠페인명 / 일 예산(원) / 광고그룹(그룹명·그룹 입찰가) / 키워드(키워드별 입찰가).
  일 예산은 (검색광고 배분 월예산 ÷ 30)을 넘지 않게. 입찰가·예산은 현실적인 '원 단위 정수'.
  네이버 검색광고가 지정 매체에 없으면 naver_searchad 값은 null 로 둔다.
- 키워드는 업종·데이터에 맞는 실제 검색 키워드로, 그룹당 5~15개.
- 전문용어는 짧은 근거로 설명한다(대표·마케터가 검토).
- 반드시 아래 JSON 형식으로만 응답한다(다른 텍스트·코드펜스·설명 금지):

{
 "summary": "한 줄 제안 요약(80자 이내, 두괄식)",
 "objective": "이 캠페인안의 핵심 목표",
 "channel_mix": [
   {"channel": "naver_searchad", "label": "네이버 검색광고", "pct": 40, "monthly_budget": 4000000, "rationale": "이 비중·예산의 근거"}
 ],
 "naver_searchad": {
   "campaign_name": "캠페인명",
   "daily_budget": 130000,
   "ad_groups": [
     {"name": "광고그룹명", "bid": 350, "keywords": [{"text": "키워드", "bid": 400}]}
   ]
 },
 "creative_directions": ["소재·메시지 방향 불릿 2~4개"],
 "expected": {"roas": 420, "monthly_clicks": 5200, "monthly_conversions": 160},
 "notes": "주의·가정·검토 포인트(특히 데이터가 부족했다면 그 사실)"
}"""


# 매체 키 → 사람 읽는 이름(프롬프트용)
CH_LABELS = {
    "naver_searchad": "네이버 검색광고", "naver_commerce": "네이버 커머스",
    "meta_ads": "메타 광고(인스타·페북)", "kakao": "카카오모먼트", "coupang_ads": "쿠팡애즈",
    "naver_gfa": "네이버 GFA", "meta_chehum": "메타체험단", "youtube": "유튜브",
    "daangn": "당근", "toss_ads": "토스애즈", "mobon": "모비온",
}


def generate(client_name: str, category: str, objective: str,
             monthly_budget: int, perf: dict, channels: list = None) -> dict:
    """실제 성과 데이터 + 목표·예산 + '진행할 매체'로 캠페인안 생성. ANTHROPIC_API_KEY 필요."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("AI 키가 아직 설정되지 않았습니다. 관리자(대표)에게 문의하세요.")

    chs = [c for c in (channels or []) if c]
    if not chs:  # 미지정이면 검색광고 단독을 기본으로(자동 적용 가능 매체)
        chs = ["naver_searchad"]
    ch_lines = ", ".join(f"{k}({CH_LABELS.get(k, k)})" for k in chs)
    sa_note = ("네이버 검색광고가 지정 매체에 포함되어 있으니 naver_searchad 블록을 채워라."
               if "naver_searchad" in chs else
               "네이버 검색광고는 지정 매체에 없으니 naver_searchad 는 null 로 둔다.")

    user_msg = (
        f"광고주: {client_name} (업종: {category or '미상'})\n"
        f"목표: {objective or '매출 성장'}\n"
        f"월 광고 예산: {int(monthly_budget):,}원\n"
        f"★진행할 매체(이 매체로만 channel_mix 구성, 지정 외 매체 금지): {ch_lines}\n"
        f"{sa_note}\n"
        f"아래는 최근 연동 매체별 성과 데이터(JSON)다. 이를 근거로 다음 기간 캠페인안을 설계하라.\n"
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
            "max_tokens": 3000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"AI 호출 실패 ({r.status_code}): {r.text[:300]}")
    text = "".join(
        b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    if "}" in text:
        text = text[: text.rfind("}") + 1]
    return json.loads(text)
