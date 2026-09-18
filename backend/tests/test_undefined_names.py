"""정의되지 않은 이름 잡기 — 배포 게이트 (2026-09-18 신설)

왜 있나
  배포 #443 에서 `_run_contam_20260917_cleanup()` 이 `DB_PATH` 를 쓰는데 그 이름이
  **이 파일의 모듈 전역에 없어** 서버에서 `NameError` 로 통째로 실패했다.
  문법은 멀쩡했고(`py_compile` 통과), 기존 회귀 시험은 **소스 글자만** 봤기 때문에
  게이트 16종이 전부 green 인 채로 나갔다.

  ⭐ 이 저장소에서 **두 번째**다 — 확장 쪽에서도 `pushLog`(실제 이름은 `log`)를
     같은 방식으로 흘려보낸 적이 있다. 그래서 「부르는 이름이 실재하는가」를
     한 번에 지키는 자를 만든다.

무엇을 보나
  backend/*.py 전 파일의 함수 안에서 **읽는(Load) 이름**이 하나라도
  ⑴ 파이썬 기본 이름 ⑵ 모듈 최상위에서 정의된 이름 ⑶ 그 함수(또는 바깥 함수)가
  묶는 이름 ⑷ 람다 매개변수·내포(comprehension) 변수 중 어디에도 없으면 실패.

⚠️ 표준 라이브러리(ast)만 쓴다 — 게이트 환경에 fastapi·pyflakes 가 없다.
⚠️ 실행 안 해도 잡는다(읽기 전용·import 0). 서버에 붙지 않는다.
⚠️ 한계 — `globals()[...]`·`exec`·`setattr` 로 만드는 이름은 못 본다.
   그건 이 저장소에 없고, 생기면 이 시험이 먼저 알려 준다(그때 예외를 적을 것).
"""
import ast
import builtins
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FN = (ast.FunctionDef, ast.AsyncFunctionDef)
COMP = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SKIP = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _bound(fn):
    """이 함수 안에서 묶이는 이름 — 매개변수·대입·import·for·with·except·중첩 def."""
    b = set()
    a = fn.args
    for x in list(a.args) + list(a.kwonlyargs) + list(getattr(a, "posonlyargs", [])):
        b.add(x.arg)
    if a.vararg:
        b.add(a.vararg.arg)
    if a.kwarg:
        b.add(a.kwarg.arg)
    for x in ast.walk(fn):
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            b.add(x.id)
        elif isinstance(x, ast.Import):
            for al in x.names:
                b.add((al.asname or al.name).split(".")[0])
        elif isinstance(x, ast.ImportFrom):
            for al in x.names:
                b.add(al.asname or al.name)
        elif isinstance(x, ast.ExceptHandler) and x.name:
            b.add(x.name)
        elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b.add(x.name)
        elif isinstance(x, (ast.Global, ast.Nonlocal)):
            for nm in x.names:
                b.add(nm)
    return b


def undefined_names(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    mod = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}

    # ⚠️ 모듈 전역은 **최상위 문장만** 본다. ast.walk 로 함수 안까지 내려가면
    #    다른 함수의 지역 대입(예: 그 파일 여러 곳의 DB_PATH)이 전역으로 잘못 잡혀,
    #    바로 이 시험이 잡아야 할 결함을 못 본다(만들면서 실제로 그랬다).
    def top(node):
        if isinstance(node, _SKIP):
            mod.add(node.name)
            return
        if isinstance(node, ast.Import):
            for al in node.names:
                mod.add((al.asname or al.name).split(".")[0])
            return
        if isinstance(node, ast.ImportFrom):
            for al in node.names:
                mod.add(al.asname or al.name)
            return
        for x in ast.iter_child_nodes(node):
            top(x)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            mod.add(node.id)
        if isinstance(node, ast.ExceptHandler) and node.name:
            mod.add(node.name)

    for node in tree.body:
        top(node)

    bad = []

    def walk(fn, outer):
        scope = outer | _bound(fn)          # 바깥 함수(클로저)까지 물려받는다
        nested = []

        def scan(node, sc):
            # ⚠️ 중첩 함수 본문은 여기서 보지 않는다 — 그 매개변수가 바깥 눈으로는
            #    미정의로 보인다(만들면서 `text` 로 헛걸렸다). 아래에서 따로 본다.
            if isinstance(node, FN) and node is not fn:
                nested.append(node)
                return
            # 람다·내포도 제 나름의 이름을 묶는다 — 안 세면 x·r 같은 흔한 이름이
            # 전부 「미정의」로 나와 경보가 쓸모없어진다.
            if isinstance(node, ast.Lambda):
                a = node.args
                sc = sc | {v.arg for v in list(a.args) + list(a.kwonlyargs)
                           + list(getattr(a, "posonlyargs", []))}
                if a.vararg:
                    sc = sc | {a.vararg.arg}
                if a.kwarg:
                    sc = sc | {a.kwarg.arg}
            elif isinstance(node, COMP):
                extra = set()
                for g in node.generators:
                    for t in ast.walk(g.target):
                        if isinstance(t, ast.Name):
                            extra.add(t.id)
                sc = sc | extra
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in sc:
                bad.append((fn.name, node.id, node.lineno))
            for x in ast.iter_child_nodes(node):
                scan(x, sc)

        for st in fn.body:
            scan(st, scope)
        for n2 in nested:
            walk(n2, scope)

    for n in tree.body:
        if isinstance(n, FN):
            walk(n, mod)
    return sorted(set(bad), key=lambda t: t[2])


_p = _f = 0


def ok(name, cond):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS  {name}")
    else:
        _f += 1
        print(f"  FAIL  {name}")


print("\n[정의되지 않은 이름 — backend/*.py 전수]")

files = sorted(f for f in os.listdir(ROOT) if f.endswith(".py"))
ok("검사할 파일이 있다(경로가 틀리면 0개로 조용히 통과한다)", len(files) >= 20)

total = 0
for f in files:
    try:
        found = undefined_names(os.path.join(ROOT, f))
    except SyntaxError as e:
        ok(f"{f} — 파싱된다", False)
        print(f"     {e}")
        continue
    total += len(found)
    ok(f"{f} — 미정의 이름 0건", not found)
    for fn, nm, ln in found:
        print(f"     {f}:{ln}  {fn}() 가 '{nm}' 을 부르는데 그 이름이 없다")

print(f"\n  (합계 미정의 이름 {total}건)")

# ── 자가 검증 — 이 자가 실제로 잡는가(일부러 고장 낸 코드를 넣어 본다) ────────
# ⚠️ 이 블록이 없으면, 검사기가 조용히 아무것도 안 잡게 되어도 게이트는 계속 green 이다.
import tempfile

with tempfile.TemporaryDirectory() as d:
    broken = os.path.join(d, "broken.py")
    io.open(broken, "w", encoding="utf-8").write(
        "def f():\n"
        "    import os\n"
        "    return os.path.join(MISSING_NAME, 'x')\n")
    got = undefined_names(broken)
    ok("자가 검증 ① — 없는 이름을 잡는다",
       any(nm == "MISSING_NAME" for _fn, nm, _ln in got))

    fine = os.path.join(d, "fine.py")
    io.open(fine, "w", encoding="utf-8").write(
        "import os\n"
        "BASE = '/app'\n"
        "def outer(text):\n"
        "    def inner(msg):\n"
        "        return msg + text + BASE\n"
        "    rows = [x for x in range(3)]\n"
        "    return inner('a') + str(sorted(rows, key=lambda r: -r))\n"
        "def uses_local():\n"
        "    p = os.getenv('P', '/tmp')\n"
        "    try:\n"
        "        return p\n"
        "    except OSError as e:\n"
        "        return str(e)\n")
    ok("자가 검증 ② — 멀쩡한 코드를 헛잡지 않는다(클로저·내포·람다·except)",
       undefined_names(fine) == [])

print(f"\n{'❌ 실패 ' + str(_f) if _f else '✅'} 통과 {_p} · 실패 {_f}")
sys.exit(1 if _f else 0)
