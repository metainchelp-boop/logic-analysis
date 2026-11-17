"""AI 채팅 검색량 · 연관 키워드 직접 조회(2026-11-18 · 대표 신고 「검색량 물어보니까 답변도 제대로 못하는데?」) 회귀.

채팅은 우리 분석 기록에 있는 키워드만 참고 자료로 받아, 처음 묻는 키워드는
「실시간 데이터에 접근할 수 없다」고 답했다. 이제
  ① AI 가 keyword_volume · related_keywords 도구로 네이버 검색광고 자료를 직접 조회한다
  ② 도구가 실패해도 채팅은 멈추지 않고, AI 에 「못 가져왔다」고 알린다(수치를 지어내지 않게)
  ③ 한 질문에서 도구는 최대 3번까지
  ④ 08:30 자동 분석 · 채팅이 쓰는 연관 키워드 조회도 띄어 쓴 키워드의 공백을 빼고 묻는다(#371 과 같은 규칙)
  ⑤ 안내문의 낡은 「400위까지 자동 추적」을 지금 사실(수집 쉼)로 고쳤다

외부 네트워크 0 · DB 0. anthropic · fastapi 가 깔린 곳에서만 채팅 함수를 실제로 부른다.
"""
import os
import re
import sys
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("JWT_SECRET_KEY", "offline-chat-tools-test-only")

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

# ── 소스 ──
ch = read(BACKEND / "chat.py")
check("안내문 · 낡은 「400위까지」 자동 추적 문구가 없다", "400위까지" not in ch)
check("안내문 · 수집 쉼(2026-11-05) · 마지막 기록 값이라고 말하게", "2026-11-05" in ch and "마지막으로 기록된 값" in ch)
check("안내문 · 검색량은 도구로 직접 조회 · 「접근할 수 없다」 금지 · 지어내지 말 것",
      "keyword_volume 도구로" in ch and "접근할 수 없다」고 답하지 마세요" in ch and "수치를 지어내지 마세요" in ch)
check("호출 · 도구를 함께 보낸다", "tools=CHAT_TOOLS," in ch)
check("호출 · 도구 묶음 최대 3번", "CHAT_TOOL_MAX_ROUNDS = 3" in ch and "_rounds < CHAT_TOOL_MAX_ROUNDS" in ch)
check("호출 · 쇼핑 검색 API(종료) · 수집기를 부르지 않는다",
      "search_naver_shopping_api" not in ch[ch.index("CHAT_TOOL_MAX_ROUNDS"):ch.index("# ==================== DB 초기화")])
aa = read(BACKEND / "auto_analysis.py")
check("연관 키워드 · 공백을 빼고 묻는다(08:30 자동 분석 · 채팅)",
      '"hintKeywords": (keyword or "").strip().replace(" ", "")' in aa and '"hintKeywords": keyword,' not in aa)
dy = read(ROOT / ".github" / "workflows" / "deploy.yml")
check("배포 · 이 시험이 게이트에 등록됨", "test_chat_tools.py" in dy)

# ── ④ 연관 키워드 공백 — 실제 함수로(requests 는 가짜) ──
try:
    import requests  # noqa: F401
    import auto_analysis
    import naver_crawler
except Exception as e:
    skipped += 1
    print(f"  SKIP  연관 키워드 실제 실행 — 의존성 없음({type(e).__name__})")
else:
    seen = {}
    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"keywordList": [
                {"relKeyword": "수제부각", "monthlyPcQcCnt": 120, "monthlyMobileQcCnt": 880, "compIdx": "낮음"},
                {"relKeyword": "수제부각선물", "monthlyPcQcCnt": 30, "monthlyMobileQcCnt": 300, "compIdx": "낮음"},
            ]}
    def _get(url, params=None, headers=None, timeout=None):
        seen["params"] = dict(params or {})
        return _R()
    with mock.patch.object(naver_crawler, "SEARCHAD_API_KEY", "k"), \
         mock.patch.object(naver_crawler, "SEARCHAD_SECRET_KEY", "s"), \
         mock.patch.object(naver_crawler, "SEARCHAD_CUSTOMER_ID", "c"), \
         mock.patch("requests.get", _get):
        out = auto_analysis.get_related_keywords(" 수제 부각 ")
    check("연관 키워드 · 띄어 쓴 키워드는 공백을 빼고 묻는다",
          seen.get("params", {}).get("hintKeywords") == "수제부각", seen)
    check("연관 키워드 · 결과가 나온다", out.get("total_found") == 2, out)

# ── ①②③ 채팅 실제 실행 ──
try:
    import anthropic  # noqa: F401
    import chat
except Exception as e:
    skipped += 1
    print(f"  SKIP  채팅 함수 실제 실행 — 의존성 없음({type(e).__name__})")
else:
    import claude_models as cm

    # 도구 함수 — 검색량
    rows = [{"keyword": "메타아이앤씨", "monthlyPcQcCnt": 40, "monthlyMobileQcCnt": 210,
             "monthlyAvePcClkCnt": 1.2, "monthlyAveMobileClkCnt": 3.4, "plAvgDepth": 2, "compIdx": "낮음"}]
    calls = []
    def _vol(kws):
        calls.append(list(kws))
        return [r for r in rows if r["keyword"] in kws]
    with mock.patch.object(naver_crawler, "get_keyword_volume", _vol):
        res = json.loads(chat._run_chat_tool("keyword_volume", {"keywords": ["메타아이앤씨", "없는키워드", "메타아이앤씨", "a", "b", "c", "d"]}))
    check("검색량 도구 · PC · 모바일 · 합계 · 경쟁 정도",
          res["results"] and res["results"][0]["monthly_total"] == 250 and res["results"][0]["monthly_pc"] == 40
          and res["results"][0]["competition"] == "낮음", res)
    check("검색량 도구 · 못 받은 키워드는 not_found(지어내지 않음)", "없는키워드" in res["not_found"], res)
    check("검색량 도구 · 겹친 키워드 빼고 최대 5개만 묻는다", calls and len(calls[0]) == 5 and calls[0].count("메타아이앤씨") == 1, calls)

    def _boom(kws):
        raise RuntimeError("네트워크")
    with mock.patch.object(naver_crawler, "get_keyword_volume", _boom):
        res = json.loads(chat._run_chat_tool("keyword_volume", {"keywords": ["x"]}))
    check("검색량 도구 · 조회가 터져도 채팅은 계속 · 오류를 알림", "error" in res, res)
    check("도구 · 모르는 도구 이름은 오류로", "error" in json.loads(chat._run_chat_tool("zzz", {})))

    # 도구 함수 — 연관 키워드
    rel = {"seed_keyword": "부각", "total_found": 3,
           "golden_keywords": [{"keyword": "수제부각", "totalVolume": 1000, "compIdx": "낮음"}],
           "related_keywords": [{"keyword": "부각", "totalVolume": 9000, "compIdx": "높음"}]}
    with mock.patch.object(auto_analysis, "get_related_keywords", lambda k: rel):
        res = json.loads(chat._run_chat_tool("related_keywords", {"keyword": "부각"}))
    check("연관 키워드 도구 · 황금 · 연관 목록", res["golden_keywords"][0]["keyword"] == "수제부각"
          and res["related_keywords"][0]["monthly_total"] == 9000, res)
    with mock.patch.object(auto_analysis, "get_related_keywords", lambda k: {"total_found": 0}):
        res = json.loads(chat._run_chat_tool("related_keywords", {"keyword": "부각"}))
    check("연관 키워드 도구 · 0건이면 「못 가져왔다」 메모", "note" in res, res)

    # 도구 묶음 — AI 가 도구를 부르면 실행해 결과를 돌려주고 다시 묻는다
    class _Usage: input_tokens = 1; output_tokens = 1
    def _tool_resp(i):
        return SimpleNamespace(stop_reason="tool_use", usage=_Usage(), content=[
            SimpleNamespace(type="text", text="잠시만요"),
            SimpleNamespace(type="tool_use", id=f"t{i}", name="keyword_volume", input={"keywords": ["메타아이앤씨"]})])
    def _text_resp(t):
        return SimpleNamespace(stop_reason="end_turn", usage=_Usage(), content=[SimpleNamespace(type="text", text=t)])

    class _Client:
        def __init__(self, plan):
            self.plan = list(plan); self.calls = []
            outer = self
            class _M:
                def create(self, **kw):
                    outer.calls.append(kw)
                    return outer.plan.pop(0) if outer.plan else _tool_resp(99)
            self.messages = _M()

    def _run(plan):
        cm.reset_unavailable()
        cl = _Client(plan)
        orig = chat._get_claude_client
        chat._get_claude_client = lambda: cl
        try:
            with mock.patch.object(naver_crawler, "get_keyword_volume", _vol):
                return chat._call_claude_sync([], "메타아이앤씨 검색량 얼마야"), cl.calls
        finally:
            chat._get_claude_client = orig

    out, cs = _run([_tool_resp(1), _text_resp("월 250건 정도예요")])
    check("묶음 · 도구 실행 뒤 다시 물어 최종 답을 돌려준다", out == "월 250건 정도예요" and len(cs) == 2, (out, len(cs)))
    check("묶음 · 도구 목록을 함께 보낸다", all("tools" in c and c["tools"] is chat.CHAT_TOOLS for c in cs))
    second = cs[1]["messages"]
    tr = second[-1]["content"][0] if isinstance(second[-1]["content"], list) else {}
    check("묶음 · 두 번째 요청에 도구 결과(검색량 250)가 실려 간다",
          second[-2]["role"] == "assistant" and tr.get("type") == "tool_result" and tr.get("tool_use_id") == "t1"
          and json.loads(tr["content"])["results"][0]["monthly_total"] == 250, tr)
    out, cs = _run([])
    check("묶음 · 도구만 계속 부르면 3번에서 멈춘다(무한 반복 없음)", len(cs) == 4, len(cs))
    out, cs = _run([_text_resp("바로 답")])
    check("묶음 · 도구가 필요 없으면 한 번에 답", out == "바로 답" and len(cs) == 1)
    cm.reset_unavailable()

    # 진짜 anthropic 라이브러리로 — 요청 모양(도구 · 도구 결과 되돌려 보내기)이 실제로 직렬화되는가.
    # 네트워크 대신 가짜 전송 계층(httpx.MockTransport)이 받는다.
    # anthropic 2.x 는 httpx2 를 쓴다(그 전 판은 httpx) — 라이브러리가 쓰는 쪽으로 가짜 전송 계층을 만든다.
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    sent = []
    def _handler(request):
        body = json.loads(request.content.decode("utf-8"))
        sent.append(body)
        if len(sent) == 1:
            payload = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                       "stop_reason": "tool_use", "stop_sequence": None,
                       "usage": {"input_tokens": 10, "output_tokens": 5},
                       "content": [{"type": "text", "text": "조회해 볼게요"},
                                   {"type": "tool_use", "id": "toolu_1", "name": "keyword_volume",
                                    "input": {"keywords": ["메타아이앤씨"]}}]}
        else:
            payload = {"id": "msg_2", "type": "message", "role": "assistant", "model": body["model"],
                       "stop_reason": "end_turn", "stop_sequence": None,
                       "usage": {"input_tokens": 20, "output_tokens": 8},
                       "content": [{"type": "text", "text": "월 250건이에요"}]}
        return httpx.Response(200, json=payload)
    real = anthropic.Anthropic(api_key="test-key", base_url="https://example.invalid",
                               http_client=httpx.Client(transport=httpx.MockTransport(_handler)), max_retries=0)
    orig = chat._get_claude_client
    chat._get_claude_client = lambda: real
    try:
        with mock.patch.object(naver_crawler, "get_keyword_volume", _vol):
            out = chat._call_claude_sync([], "메타아이앤씨 검색량 얼마야")
    finally:
        chat._get_claude_client = orig
    check("실제 라이브러리 · 최종 답", out == "월 250건이에요", out)
    check("실제 라이브러리 · 첫 요청에 도구 2개 정의가 실린다",
          len(sent) == 2 and [t["name"] for t in sent[0].get("tools", [])] == ["keyword_volume", "related_keywords"], sent[:1])
    if len(sent) == 2:
        m = sent[1]["messages"]
        check("실제 라이브러리 · 두 번째 요청 = 앞 답(도구 호출 포함) + 도구 결과",
              m[-2]["role"] == "assistant" and any(b.get("type") == "tool_use" for b in m[-2]["content"])
              and m[-1]["content"][0]["type"] == "tool_result" and m[-1]["content"][0]["tool_use_id"] == "toolu_1"
              and json.loads(m[-1]["content"][0]["content"])["results"][0]["monthly_total"] == 250, m[-2:])
    cm.reset_unavailable()

socket.socket.connect = _real_connect
print(f"\n결과: {passed} 통과 · {failed} 실패 · {skipped} 건너뜀")
sys.exit(1 if failed else 0)
