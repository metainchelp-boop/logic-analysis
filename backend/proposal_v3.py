"""맞춤제안서 v3 — 인계 자료에 「제안서 재료(facts)」와 「문장(copy)」을 붙인다 (2026-10-26).

부르는 곳: main.py `/api/sales-bundle` 보관 직전 — payload 에 `v3: true` 가 있을 때만.
⚠️ 무엇이 실패해도 **인계 자체는 막지 않는다** — 원래 자료를 그대로 보관하고,
   제안서 화면은 facts 가 없으면 「자료를 다시 받아 주세요」로 안내한다.
⚠️ 표준 라이브러리만 쓴다(배포 게이트 환경에 fastapi·anthropic 이 없다).
"""
import logging
import os

import proposal_copy
import proposal_facts

logger = logging.getLogger(__name__)


def enrich(payload, api_key=None, client=None, now=None):
    """payload 를 고치지 않고 facts·copy 를 붙인 **새 dict** 를 돌려준다. v3 가 아니면 그대로."""
    if not isinstance(payload, dict) or not payload.get("v3"):
        return payload
    out = dict(payload)
    try:
        facts = proposal_facts.build(payload, now=now)
    except Exception as e:  # 재료를 못 만들면 문장도 못 만든다 — 원본만 보관
        logger.warning(f"[제안서v3] 재료 정리 실패: {e}")
        out["v3Error"] = "facts"
        return out
    out["facts"] = facts
    try:
        key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
        res = proposal_copy.generate(facts, api_key=key or None, client=client)
        out["copy"] = res.get("copy") or {}
        out["copyMeta"] = {"source": res.get("source") or {}, "aiProblems": res.get("aiProblems") or []}
    except Exception as e:
        logger.warning(f"[제안서v3] 문장 생성 실패 — 규칙 문장으로: {e}")
        out["copy"] = proposal_copy.template(facts)
        out["copyMeta"] = {"source": {"template": True}, "aiProblems": ["generate-failed"]}
    return out
