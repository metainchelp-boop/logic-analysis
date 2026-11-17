"""AI 모델 이름 고침(2026-11-17 · 대표 「권고대로해」) 회귀.

서버 .env 의 CLAUDE_MODEL 이 은퇴한 `claude-sonnet-4-20250514` 로 남아
  - AI 채팅은 매번 「AI 응답을 받지 못했습니다」
  - 경쟁사 비교 코칭은 매번 첫 시도가 실패
하던 것을 고쳤는지 본다.
  ⓐ 배포가 .env 의 그 값만 claude-sonnet-4-6 으로 바꾼다(다른 값은 손대지 않음)
  ⓑ 채팅 · 코칭이 「없음(404)」이면 대체 모델로 다시 묻는다 · 다른 실패는 넘기지 않는다

외부 네트워크 0 · DB 0. anthropic · fastapi 가 깔린 곳에서는 채팅 함수를 실제로 불러 확인하고,
없는 곳(배포 회귀 게이트)에서는 그 부분만 건너뛰고 규칙 · 소스로 확인한다.
"""
import os
import re
import sys
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("JWT_SECRET_KEY", "offline-claude-models-test-only")

_real_connect = socket.socket.connect
def _no_net(self, addr):
    raise AssertionError(f"외부 연결 금지: {addr}")
socket.socket.connect = _no_net

passed = failed = skipped = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {extra}")

def read(p):
    return Path(p).read_text(encoding="utf-8")

RETIRED = "claude-sonnet-4-20250514"

# ── 규칙 ──
import claude_models as cm

cm.reset_unavailable()
check("은퇴 모델이 설정돼 있으면 묻지 않고 대체 모델부터",
      cm.model_candidates(RETIRED) == ["claude-sonnet-4-6", "claude-haiku-4-5"], cm.model_candidates(RETIRED))
check("사람이 고른 다른 모델은 맨 앞 그대로",
      cm.model_candidates("claude-opus-x") == ["claude-opus-x", "claude-sonnet-4-6", "claude-haiku-4-5"])
check("설정이 대체 모델과 같으면 겹치지 않음",
      cm.model_candidates("claude-sonnet-4-6") == ["claude-sonnet-4-6", "claude-haiku-4-5"])
check("빈 설정이면 대체 모델", cm.model_candidates("") == ["claude-sonnet-4-6", "claude-haiku-4-5"])
cm.mark_unavailable("claude-opus-x", "시험")
check("「없음」이 난 모델은 다음부터 건너뜀",
      cm.model_candidates("claude-opus-x") == ["claude-sonnet-4-6", "claude-haiku-4-5"])
cm.mark_unavailable("claude-sonnet-4-6", "시험"); cm.mark_unavailable("claude-haiku-4-5", "시험")
check("전부 빠지면 대체 모델이라도 다시 시도(빈 목록이 되지 않음)",
      cm.model_candidates("claude-opus-x") == ["claude-sonnet-4-6", "claude-haiku-4-5"])
cm.reset_unavailable()

class _E(Exception):
    def __init__(self, code):
        super().__init__(f"code {code}")
        self.status_code = code
check("404 · 403 만 「모델 없음」", cm.is_model_missing_error(_E(404)) and cm.is_model_missing_error(_E(403)))
check("시간 초과 · 요청 많음 · 서버 오류는 다른 모델로 넘기지 않음",
      not cm.is_model_missing_error(_E(429)) and not cm.is_model_missing_error(_E(500))
      and not cm.is_model_missing_error(_E(400)) and not cm.is_model_missing_error(ValueError("x")))
check("claude_models 는 anthropic 을 불러오지 않음(게이트에서도 돔)",
      "import anthropic" not in read(BACKEND / "claude_models.py"))

# ── 소스 ──
ch = read(BACKEND / "chat.py")
check("채팅 · 대체 모델 목록으로 묻는다", "for _mdl in model_candidates(CLAUDE_MODEL):" in ch
      and "model=_mdl," in ch)
check("채팅 · 「없음」이 아니면 그대로 올려 보낸다(시간 초과 · 요청 많음 문구 유지)",
      "if not is_model_missing_error(_e):\n                    raise" in ch)
check("채팅 · 예전처럼 설정 모델 하나만 묻는 줄이 없다", "model=CLAUDE_MODEL," not in ch)
cd = read(BACKEND / "client_dashboard.py")
check("코칭 · 시도 목록이 claude_models 규칙", "models_to_try = model_candidates(CLAUDE_MODEL)" in cd)
check("코칭 · 「없음」이면 기억해 다음부터 건너뜀", 'mark_unavailable(mdl, "compare-coaching")' in cd)

dy = read(ROOT / ".github" / "workflows" / "deploy.yml")
check("배포 · .env 가 정확히 은퇴 모델일 때만 바꾼다",
      "grep -qx 'CLAUDE_MODEL=claude-sonnet-4-20250514' .env" in dy
      and "s/^CLAUDE_MODEL=claude-sonnet-4-20250514$/CLAUDE_MODEL=claude-sonnet-4-6/" in dy)
check("배포 · 바꾸기 전에 .env 백업", "cp .env .env.bak-claude-model" in dy)
gen = re.search(r"cat > docker-compose\.yml << 'COMPEOF'(.*?)COMPEOF", dy, re.S).group(1)
check("배포 · compose 에는 CLAUDE_MODEL 을 넣지 않음(종전 규칙 유지)",
      not re.search(r"^\s*-\s*CLAUDE_MODEL=", gen, re.M))
check("배포 · 이 시험이 게이트에 등록됨", "test_claude_models.py" in dy)

# 배포 셸 줄을 실제로 돌려 본다 — 은퇴 값만 바뀌고 다른 줄은 그대로인가
import subprocess, tempfile
seg = re.search(r"(if grep -qx 'CLAUDE_MODEL=claude-sonnet-4-20250514' \.env.*?\n\s*fi\n)", dy, re.S)
check("배포 · 고침 블록을 찾음", seg is not None)
if seg:
    script = "\n".join(l.strip() for l in seg.group(1).splitlines())
    for before, after in (
        (f"A=1\nCLAUDE_MODEL={RETIRED}\nB=2\n", "A=1\nCLAUDE_MODEL=claude-sonnet-4-6\nB=2\n"),
        ("A=1\nCLAUDE_MODEL=claude-opus-x\nB=2\n", "A=1\nCLAUDE_MODEL=claude-opus-x\nB=2\n"),
        (f"A=1\nCLAUDE_MODEL={RETIRED}x\nB=2\n", f"A=1\nCLAUDE_MODEL={RETIRED}x\nB=2\n"),
        ("A=1\nB=2\n", "A=1\nB=2\n"),
    ):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text(before, encoding="utf-8")
            subprocess.run(["bash", "-c", script], cwd=d, check=True, capture_output=True)
            got = Path(d, ".env").read_text(encoding="utf-8")
            check(f"배포 셸 · {before.splitlines()[1] if len(before.splitlines()) > 2 else '(CLAUDE_MODEL 없음)'} → 결과가 맞음",
                  got == after, repr(got))

# ── 채팅 함수 실제 실행(의존성이 있을 때만) ──
try:
    import anthropic
    import httpx
    import chat
except Exception as e:  # 게이트에는 fastapi · anthropic 이 없다
    skipped += 1
    print(f"  SKIP  채팅 함수 실제 실행 — 의존성 없음({type(e).__name__})")
else:
    def _err(cls, code):
        req = httpx.Request("POST", "https://example.invalid/v1/messages")
        return cls("x", response=httpx.Response(code, request=req), body=None)

    class _Usage: input_tokens = 1; output_tokens = 1
    class _Block:
        def __init__(self, t): self.text = t
    class _Resp:
        def __init__(self, t): self.content = [_Block(t)]; self.usage = _Usage()

    class _Client:
        def __init__(self, plan):
            self.plan = plan; self.asked = []
            outer = self
            class _M:
                def create(self, **kw):
                    outer.asked.append(kw["model"])
                    r = outer.plan.get(kw["model"])
                    if isinstance(r, Exception):
                        raise r
                    return _Resp(r or "기본 답")
            self.messages = _M()

    def _run(plan, configured):
        cm.reset_unavailable()
        cl = _Client(plan)
        orig_get, orig_model = chat._get_claude_client, chat.CLAUDE_MODEL
        chat._get_claude_client = lambda: cl
        chat.CLAUDE_MODEL = configured
        try:
            return chat._call_claude_sync([], "안녕"), cl.asked
        finally:
            chat._get_claude_client, chat.CLAUDE_MODEL = orig_get, orig_model

    out, asked = _run({"claude-sonnet-4-6": "답 4-6"}, RETIRED)
    check("실행 · 은퇴 모델 설정이어도 채팅이 답한다(은퇴 모델은 묻지도 않음)",
          out == "답 4-6" and asked == ["claude-sonnet-4-6"], (out, asked))
    out, asked = _run({"claude-x": _err(anthropic.NotFoundError, 404), "claude-sonnet-4-6": "답 4-6"}, "claude-x")
    check("실행 · 설정 모델이 「없음」이면 대체 모델로 답한다",
          out == "답 4-6" and asked == ["claude-x", "claude-sonnet-4-6"], (out, asked))
    out, asked = _run({"claude-x": _err(anthropic.RateLimitError, 429)}, "claude-x")
    check("실행 · 요청 많음은 다른 모델로 넘기지 않고 종전 문구",
          asked == ["claude-x"] and "30초 후" in out, (out, asked))
    nf = _err(anthropic.NotFoundError, 404)
    out, asked = _run({"claude-x": nf, "claude-sonnet-4-6": nf, "claude-haiku-4-5": nf}, "claude-x")
    check("실행 · 모두 「없음」이면 종전 실패 문구",
          "AI 응답을 받지 못했습니다" in out and len(asked) == 3, (out, asked))
    cm.reset_unavailable()

socket.socket.connect = _real_connect
print(f"\n결과: {passed} 통과 · {failed} 실패 · {skipped} 건너뜀")
sys.exit(1 if failed else 0)
