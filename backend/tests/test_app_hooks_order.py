"""App.jsx 훅 순서 회귀 시험 (2026-09-15)

무엇을 막는가 — **early return 뒤에 훅을 두는 것.**

`App.jsx` 는 로그인 전에 두 번 일찍 돌아간다:

    if (authChecking) return <스피너>
    if (!currentUser) return <LoginPage>

React 는 렌더마다 훅이 **같은 수·같은 순서**로 불려야 한다. 그 뒤에 훅을 두면
로그인 화면(훅 N개) → 로그인 뒤 화면(훅 N+k개)으로 넘어가는 순간
「Rendered more hooks than during the previous render」(minified #310) 이 나고
ErrorBoundary 가 **「화면 로드 오류」** 를 띄운다.

2026-09-15 실사고 — 영업 자료 동시 생성용 useRef·useEffect 를 그 뒤에 두고 배포(14:19).
`both=1` 이 아닐 때는 「한 줄도 돌지 않는다」고 적어 두었지만, **훅 호출 자체**는 조건과
무관하게 일어난다. 로직분석 **전체**가 로그인 직후 죽었고 영업팀이 14:43 에 신고했다.
새로고침 버튼도 같은 자리에서 다시 죽으니 직원이 스스로 빠져나올 길이 없었다.

⭐ 교훈 — 「이 블록은 조건이 아니면 안 돈다」와 「이 훅은 조건이 아니면 안 불린다」는 다른 말이다.
   훅은 **정의된 자리**에서 무조건 불린다. 자리가 곧 계약이다.

이 시험이 지키는 것:
  ① App.jsx 의 첫 early return(코드 줄) 뒤에 훅 호출이 **0개**인가 — 주석은 벗기고 센다
  ② 동시 생성 훅(_oneShotDone·_runOneShotRef·그 useEffect)이 early return **앞**에 있는가
  ③ early return 뒤에서 정의되는 _runOneShot 을 ref 로 넘겨 주는 줄이 있는가
  ④ 이 시험이 배포 게이트에 등록돼 있는가

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi·pyyaml 이 없다).
⚠️ 주석을 벗기는 이유 — 경고 주석이 「if (authChecking) return」「useEffect」 를 그대로 적는다.
   벗기지 않으면 주석이 코드로 잡혀 시험이 스스로 속는다(만들면서 실제로 한 번 속았다).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
APP = os.path.join(ROOT, "frontend", "js", "components", "App.jsx")

_pass = _fail = 0


def ok(name, cond, note=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}" + (f"  — {note}" if note else ""))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def strip_comments(src):
    """블록 주석·줄 주석을 같은 줄 수로 지운다(줄 번호를 보존해 FAIL 이 가리키는 줄이 맞게)."""
    def _blank_keep_newlines(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    src = re.sub(r"/\*.*?\*/", _blank_keep_newlines, src, flags=re.S)
    src = re.sub(r"(?m)^(\s*)//.*$", r"\1", src)
    # 코드 뒤에 붙은 // 주석 — 문자열 안의 http:// 는 살린다
    src = re.sub(r"(?m)(?<![:'\"])//(?![^\n]*['\"]).*$", "", src)
    return src


HOOK_RE = re.compile(r"(?:React\.)?use(?:State|Effect|Ref|Callback|Memo|Context|Reducer|LayoutEffect)\s*\(")
EARLY_RETURN_RE = re.compile(r"^    if \((?:authChecking|!currentUser)\) return ", re.M)


def app_lines():
    return strip_comments(read("frontend", "js", "components", "App.jsx")).split("\n")


# ==================================================================
# ① early return 뒤에 훅이 없는가
# ==================================================================
def test_no_hooks_after_early_return():
    lines = app_lines()
    first = next((i for i, l in enumerate(lines) if EARLY_RETURN_RE.match(l)), None)
    ok("App.jsx 에 로그인 전 early return 이 있다(시험의 전제)", first is not None,
       "없어졌다면 이 시험의 앵커를 다시 잡을 것")
    if first is None:
        return
    after = [(i + 1, l.strip()) for i, l in enumerate(lines) if i > first and HOOK_RE.search(l)]
    ok(f"early return({first + 1}행) 뒤에 훅 호출이 0개다",
       not after,
       "뒤에 있으면 로그인 직후 React #310 으로 전체 화면이 죽는다 → " + "; ".join(f"{n}행 {t[:60]}" for n, t in after[:5]))


# ==================================================================
# ② 동시 생성 훅이 early return 앞에 있는가
# ==================================================================
def test_oneshot_hooks_before_early_return():
    lines = app_lines()
    first = next((i for i, l in enumerate(lines) if EARLY_RETURN_RE.match(l)), None)
    if first is None:
        return
    def line_of(pat):
        return next((i for i, l in enumerate(lines) if pat in l), None)
    done = line_of("var _oneShotDone = React.useRef(")
    ref = line_of("var _runOneShotRef = React.useRef(")
    ok("_oneShotDone useRef 가 있고 early return 앞이다", done is not None and done < first,
       "옮겨졌거나 지워졌다")
    ok("_runOneShotRef useRef 가 있고 early return 앞이다", ref is not None and ref < first,
       "옮겨졌거나 지워졌다")
    # 그 useEffect — _runOneShotRef.current 를 부르는 효과가 early return 앞에 있어야 한다
    call = line_of("_runOneShotRef.current(S)")
    ok("동시 생성 useEffect(ref 호출)가 early return 앞이다", call is not None and call < first,
       "효과 본문이 early return 뒤로 내려갔다")
    # 효과가 로그인 전에 도는 일이 없게
    guard = line_of("if (!currentUser) return;")
    ok("동시 생성 useEffect 가 로그인 전에는 아무것도 안 한다(currentUser 가드)",
       guard is not None and guard < first,
       "로그인 화면에서 폴링이 시작될 수 있다")


# ==================================================================
# ③ _runOneShot 최신본을 ref 로 넘기는가
# ==================================================================
def test_runoneshot_ref_assignment():
    src = strip_comments(read("frontend", "js", "components", "App.jsx"))
    d = src.find("var _runOneShot = function(S) {")
    a = src.find("_runOneShotRef.current = _runOneShot;")
    ok("_runOneShot 정의가 남아 있다", d >= 0)
    ok("_runOneShotRef.current = _runOneShot 대입이 정의 뒤에 있다", a > d >= 0,
       "없으면 효과가 undefined 를 불러 보고서가 안 나간다")


# ==================================================================
# ④ 이 시험이 배포 게이트에 등록돼 있는가
# ==================================================================
def test_self_registered_in_gate():
    me = os.path.basename(__file__)
    dy = read(".github", "workflows", "deploy.yml")
    ok(f"deploy.yml 이 {me} 를 부른다", me in dy, "만들어 놓고 안 도는 시험이 된다")


if __name__ == "__main__":
    print("=== App.jsx 훅 순서 회귀 시험 ===")
    test_no_hooks_after_early_return()
    test_oneshot_hooks_before_early_return()
    test_runoneshot_ref_assignment()
    test_self_registered_in_gate()
    print(f"\n통과 {_pass} · 실패 {_fail}")
    sys.exit(1 if _fail else 0)
