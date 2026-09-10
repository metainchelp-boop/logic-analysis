"""알림 설정 검증기 회귀 시험 (2026-09-10)

무엇을 막는가: `NameError: name 're' is not defined`.
`main.py` 는 `re` 를 **함수 안에서만** import 하고 있었다. 그런데 Pydantic 검증기는
**클래스 본문**에 있어 그 이름을 못 본다 — 전화번호를 넣고 저장할 때마다 500 이 났다.
서버 로그에도 「설정 변경 실패」가 안 남았다(예외가 try 블록 밖, 검증 단계에서 났다).
⇒ **아무도 수신 번호를 저장할 수 없었다.** 수집 멈춤 경보를 만들어 놓고도 못 받는 상태였다.

⚠️ 시험 방법이 핵심이다 — 검증기 본문만 떼어 `import re` 해서 돌리면 **항상 통과한다.**
   그래서 **main.py 의 모듈 최상단 import 만으로 이름 공간을 만들어** 그 안에서 돌린다.
   전역 import 가 없으면 운영과 똑같이 NameError 가 난다.

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi·pydantic 이 없다).
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(os.path.dirname(HERE), "main.py")
SRC = open(MAIN, encoding="utf-8").read()
TREE = ast.parse(SRC)

_pass = _fail = 0


def ok(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}")


def module_level_imports():
    """main.py **최상단**에서 import 한 모듈만 모은다(함수 안 import 는 세지 않는다)."""
    ns = {}
    for node in TREE.body:                       # body 만 본다 = 최상단
        if isinstance(node, ast.Import):
            for a in node.names:
                name = a.asname or a.name.split(".")[0]
                try:
                    ns[name] = __import__(a.name)
                except Exception:
                    pass                          # fastapi 등 게이트에 없는 것은 건너뛴다
    return ns


def grab_validator(class_name, func_name):
    """클래스 본문의 검증기 하나를 통째로 떼어 온다."""
    for node in ast.walk(TREE):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == func_name:
                    f2 = ast.FunctionDef(name=f.name, args=f.args, body=f.body,
                                         decorator_list=[], returns=None,
                                         type_comment=None, type_params=[])
                    mod = ast.Module(body=[f2], type_ignores=[])
                    ast.fix_missing_locations(mod)
                    return mod
    raise AssertionError(f"{class_name}.{func_name} 을 못 찾았다")


print("\n[알림 설정 검증기 — main.py 전역 이름만으로 돌린다]")

ns = module_level_imports()
ok("① main.py 전역에 re 가 import 돼 있다", "re" in ns)

# ② 전화번호 검증기를 **그 이름 공간에서** 실제로 돌린다
try:
    exec(compile(grab_validator("NotificationSettingsRequest", "validate_phone"),
                 "<validator>", "exec"), ns)
    validate_phone = ns["validate_phone"]
    err = None
    try:
        got = validate_phone(None, "01012345678")
    except NameError as e:
        err = e
        got = None
except Exception as e:                                   # 떼어내기 자체가 실패
    validate_phone = None
    err = e
    got = None

ok("② 번호를 넣어 부르면 NameError 가 안 난다", not isinstance(err, NameError))
if isinstance(err, NameError):
    print(f"     ↳ 운영에서 나던 그 오류가 재현됐다: {err}")

if validate_phone and not isinstance(err, NameError):
    ok("② 정상 번호를 통과시킨다", got == "01012345678")

    def rejects(v):
        try:
            validate_phone(None, v)
            return False
        except ValueError:
            return True
        except NameError:
            return False

    ok("③ 하이픈이 있어도 통과한다", validate_phone(None, "010-1234-5678") == "010-1234-5678")
    ok("③ 휴대폰이 아닌 번호는 막는다", rejects("021234567"))
    ok("③ 글자가 섞이면 막는다", rejects("공일공1234"))
    ok("④ 빈 값은 그대로 통과(지우기 허용)", validate_phone(None, "") == "")
    ok("④ 안 보낸 값(None)도 통과", validate_phone(None, None) is None)

# ⑤ 리포트 시각 검증기도 같은 함정에 있었다 — 같이 본다
try:
    exec(compile(grab_validator("NotificationSettingsRequest", "validate_report_time"),
                 "<validator>", "exec"), ns)
    vt = ns["validate_report_time"]
    e2 = None
    try:
        vt(None, "09:00")
    except NameError as e:
        e2 = e
except Exception as e:
    vt, e2 = None, e
ok("⑤ 리포트 시각 검증기도 NameError 가 안 난다", not isinstance(e2, NameError))

print("\n" + (f"❌ 실패 {_fail}건 / 전체 {_pass + _fail}" if _fail else "알림 설정 검증기 시험 전부 통과"))
sys.exit(1 if _fail else 0)
