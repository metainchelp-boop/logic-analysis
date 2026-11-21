"""Claude 모델 고르기 — 설정한 모델이 없어졌을 때 다른 모델로 다시 시도한다.

⚠️ 모델은 저절로 바뀌지 않는다. 회사가 모델을 은퇴시키면 그 이름은 「없음(404)」이 된다.
   2026-11-17 실측: 서버 .env 의 CLAUDE_MODEL 이 은퇴한 `claude-sonnet-4-20250514` 로 남아
   AI 채팅이 매번 「AI 응답을 받지 못했습니다」, 경쟁사 비교 코칭은 매번 첫 시도가 실패했다.

규칙
- 설정한 모델을 먼저 쓰고, 「없음(404) · 권한 없음(403)」이면 아래 대체 모델 순서로 다시 묻는다.
- 그 밖의 실패(시간 초과 · 요청 많음 · 서버 오류)는 다른 모델로 넘기지 않는다 — 모델 탓이 아니다.
- 한 번 「없음」이 난 모델은 이 일꾼(프로세스)에서 다시 묻지 않는다(매번 한 번씩 헛걸음 방지).
- 이 파일은 anthropic 패키지를 불러오지 않는다(시험 환경에 없어도 돌게).
"""
import logging

logger = logging.getLogger(__name__)

# 은퇴해 이름이 없어진 모델 — 설정에 남아 있어도 묻지 않는다.
RETIRED_MODELS = frozenset({
    "claude-sonnet-4-20250514",
})

# 설정한 모델이 없을 때 차례로 쓰는 모델(2026-11-17 모델 조회로 둘 다 있음 확인).
FALLBACK_MODELS = ("claude-sonnet-4-6", "claude-haiku-4-5")

# 이 일꾼에서 「없음」이 확인된 모델
_unavailable = set()


def model_candidates(configured):
    """설정한 모델 → 대체 모델 순서의 시도 목록(중복 · 은퇴 · 없음 확인된 것 제외)."""
    out = []
    for m in (configured, *FALLBACK_MODELS):
        m = (m or "").strip()
        if not m or m in out or m in RETIRED_MODELS or m in _unavailable:
            continue
        out.append(m)
    # 전부 빠졌으면(예: 열쇠 문제로 다 403) 대체 모델이라도 다시 시도한다.
    return out or list(FALLBACK_MODELS)


def is_model_missing_error(err):
    """그 모델이 없거나 쓸 수 없다는 오류인가(404 · 403). 다른 모델로 넘길 이유가 되는 것만."""
    return getattr(err, "status_code", None) in (403, 404)


def mark_unavailable(model, where=""):
    """「없음」이 난 모델을 기억한다 — 다음 요청부터 건너뛴다."""
    if model and model not in _unavailable:
        _unavailable.add(model)
        logger.warning(f"[claude-models] {where} 모델 사용 불가로 표시: {model} — 다음 요청부터 대체 모델을 먼저 씁니다")


def reset_unavailable():
    """시험용 — 기억을 비운다."""
    _unavailable.clear()
