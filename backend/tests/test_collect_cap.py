"""수집 시험 상한 회귀 (2026-09-15)

무엇을 지키나
  ① collect_cap 규칙 — env 우선·쓰레기 값은 기본값·cap 0 은 무변경·cap n 은 n개·시험 중 온디맨드 0
  ② collector.py 가 실제로 그 규칙을 **두 경로(/keywords 시간대·all)와 /requests** 에 건다(소스 검사)
  ③ 응답에 test_cap 이 실린다(팝업 로그에서 상한이 켜진 것이 보여야 끄는 것을 잊지 않는다)
  ④ 게이트 등록

⚠️ collector.py 는 fastapi 를 끌어와 게이트에서 import 가 안 된다 → 소스 검사(저장소 관례).
표준 라이브러리만 쓴다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

import collect_cap as cc  # noqa: E402

_pass = _fail = 0


def ok(name, cond, note=""):
    global _pass, _fail
    if cond:
        _pass += 1; print(f"  PASS  {name}")
    else:
        _fail += 1; print(f"  FAIL  {name}" + (f"  — {note}" if note else ""))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_rules():
    ok("기본값은 정수이고 0 이상", isinstance(cc.DEFAULT_TEST_CAP, int) and cc.DEFAULT_TEST_CAP >= 0)
    ok("env 없으면 기본값", cc.effective_cap({}) == cc.DEFAULT_TEST_CAP)
    ok("env 빈 문자열이면 기본값", cc.effective_cap({cc.ENV_KEY: "  "}) == cc.DEFAULT_TEST_CAP)
    ok("env 가 이긴다(3)", cc.effective_cap({cc.ENV_KEY: "3"}) == 3)
    ok("env 0 = 평소 운행", cc.effective_cap({cc.ENV_KEY: "0"}) == 0)
    ok("쓰레기 값은 기본값(더 위험해지지 않는다)", cc.effective_cap({cc.ENV_KEY: "abc"}) == cc.DEFAULT_TEST_CAP)
    ok("음수는 기본값", cc.effective_cap({cc.ENV_KEY: "-2"}) == cc.DEFAULT_TEST_CAP)
    kws = [f"k{i}" for i in range(40)]
    ok("cap 0 → 40개 그대로", cc.apply_cap(kws, 0) == kws)
    ok("cap 1 → 1개", cc.apply_cap(kws, 1) == ["k0"])
    ok("cap 5 → 5개", cc.apply_cap(kws, 5) == kws[:5])
    ok("cap 이 목록보다 커도 안전", cc.apply_cap(kws[:2], 9) == kws[:2])
    ok("시험 중 온디맨드 금지", cc.ondemand_allowed(1) is False)
    ok("평소엔 온디맨드 허용", cc.ondemand_allowed(0) is True)


def test_wired_in_collector():
    src = read("backend", "collector.py")
    ok("collector.py 가 collect_cap 을 import 한다", "from collect_cap import" in src)
    hourly = src.find('"mode": "hourly"')
    allmode = src.find('"mode": "all"')
    ok("시간대 경로에 _apply_cap 이 걸린다", hourly > 0 and "_apply_cap(picked" in src[:hourly + 400])
    ok("all 경로에도 _apply_cap 이 걸린다", allmode > 0 and "_apply_cap(sorted(remaining)" in src[:allmode + 50])
    req = src.find('@router.get("/requests")')
    body = src[req:req + 2500] if req > 0 else ""
    ok("/requests 가 시험 중 빈 목록을 돌려준다", "_ondemand_ok(_test_cap())" in body and '"keywords": []' in body)
    ok("/requests 의 가드가 DB 를 열기 전에 있다",
       body.find("_ondemand_ok") < body.find("sqlite3.connect") if body else False)
    ok("응답에 test_cap 이 실린다(두 경로)", src.count('"test_cap"') >= 3)


def test_self_registered_in_gate():
    me = os.path.basename(__file__)
    ok(f"deploy.yml 이 {me} 를 부른다", me in read(".github", "workflows", "deploy.yml"))


if __name__ == "__main__":
    print("=== 수집 시험 상한 회귀 ===")
    test_rules(); test_wired_in_collector(); test_self_registered_in_gate()
    print(f"\n통과 {_pass} · 실패 {_fail}")
    sys.exit(1 if _fail else 0)
