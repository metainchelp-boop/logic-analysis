"""구문 시험 — 코드 모양으로 안전 규칙을 고정한다(설계 v1.8 · 안전 규칙 1·2·11·12).

- 네트워크를 여는 코드는 ``naver_read.py`` 한 파일에만 있다(관문 밖 호출 0).
- ③ 쓰기 어댑터(``app.adapters.naver_searchad`` — 입찰·예산을 바꾸는 함수가 들어 있다)와
  ③ 앱 본체(``app.main`` · ``collector`` · ``database`` · ``security`` · ``models``)를 import 하지 않는다.
- GET 이 아닌 방식 이름(POST · PUT · DELETE · PATCH)이 엔진 코드에 한 글자도 없다.
- 요청을 만드는 곳(``Request(``)은 관문 ``_gate`` 안 한 곳뿐이다.
- 비밀값을 꺼내는 ``reveal()`` 은 관문 ``_gate`` 안에서만 부른다.
- 손잡이 서명 열쇠 ``_KEY`` 는 ``handles.py`` 밖에서 쓰지 않는다(밖에서 쓰면 손잡이를 위조할 수 있다).
"""
from __future__ import annotations

import ast
import pathlib
import re
import unittest

ENGINE = pathlib.Path(__file__).resolve().parents[1]
SOURCES = sorted(p for p in ENGINE.rglob("*.py") if "tests" not in p.parts)
NET_WORDS = re.compile(r"\b(urllib\.request|urlopen|http\.client|socket|requests|httpx|aiohttp|build_opener|"
                       r"HTTPConnection|HTTPSConnection|subprocess)\b")
FORBIDDEN_IMPORTS = ("app.adapters", "app.main", "app.collector", "app.database", "app.security", "app.models",
                     "adapters.naver_searchad", "naver_searchad")


def _src(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _code_only(p: pathlib.Path) -> str:
    """주석·문서 문자열을 뺀 코드 — 설명문에 나온 낱말로 시험이 흔들리지 않게."""
    tree = ast.parse(_src(p))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                node.body[0] = ast.Pass()
    return ast.unparse(tree)


def _enclosing_functions(tree: ast.AST):
    """노드 → 그 노드를 감싸는 함수 이름."""
    owner = {}

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            owner[child] = name
            visit(child, name)
    visit(tree, None)
    return owner


class GuardrailTest(unittest.TestCase):
    def test_sources_found(self):
        names = {p.name for p in SOURCES}
        self.assertTrue({"naver_read.py", "handles.py", "fields.py", "credentials.py"} <= names)

    def test_network_only_in_gate_module(self):
        for p in SOURCES:
            if p.name == "naver_read.py":
                continue
            hits = NET_WORDS.findall(_code_only(p))
            self.assertEqual(hits, [], f"{p.name} 에 네트워크 코드가 있다 — 관문 밖 호출 금지")

    def test_no_forbidden_imports(self):
        for p in SOURCES:
            tree = ast.parse(_src(p))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
                for m in mods:
                    for bad in FORBIDDEN_IMPORTS:
                        self.assertFalse(m == bad or m.startswith(bad + ".") or m.endswith("." + bad) or
                                         m.endswith(bad), f"{p.name}: {m} import 금지")
            self.assertNotIn("importlib", _code_only(p), f"{p.name}: 우회 import 금지")
            self.assertNotIn("__import__", _code_only(p), f"{p.name}: 우회 import 금지")

    def test_no_write_method_names(self):
        for p in SOURCES:
            code = _code_only(p)
            for word in ("POST", "PUT", "DELETE", "PATCH"):
                self.assertNotIn(f'"{word}"', code, f"{p.name}: {word}")
                self.assertNotIn(f"'{word}'", code, f"{p.name}: {word}")

    def test_single_request_builder_inside_gate(self):
        p = ENGINE / "naver_read.py"
        tree = ast.parse(_src(p))
        owner = _enclosing_functions(tree)
        builders = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and
                    ((isinstance(n.func, ast.Attribute) and n.func.attr in ("Request", "urlopen", "open")
                      and not (isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "_opener"
                               and owner.get(n) == "send")) or
                     (isinstance(n.func, ast.Name) and n.func.id in ("Request", "urlopen")))]
        self.assertEqual([owner.get(n) for n in builders], ["_gate"], "요청은 관문 한 곳에서만 만든다")
        gate_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "_gate"]
        self.assertTrue(gate_calls)
        for n in gate_calls:
            self.assertIsInstance(n.args[0], ast.Constant, "관문에는 방식 이름을 글자 그대로 넘긴다")
            self.assertEqual(n.args[0].value, "GET")
            self.assertEqual(owner.get(n), "_request", "관문은 _request 에서만 부른다")

    def test_transport_send_only_in_gate(self):
        tree = ast.parse(_src(ENGINE / "naver_read.py"))
        owner = _enclosing_functions(tree)
        sends = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "send"]
        self.assertEqual([owner.get(n) for n in sends], ["_gate"])

    def test_reveal_only_in_gate(self):
        for p in SOURCES:
            tree = ast.parse(_src(p))
            owner = _enclosing_functions(tree)
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "reveal":
                    self.assertEqual((p.name, owner.get(n)), ("naver_read.py", "_gate"),
                                     "비밀값은 관문에서만 꺼낸다")

    def test_handle_key_private(self):
        for p in SOURCES:
            if p.name == "handles.py":
                continue
            self.assertNotRegex(_code_only(p), r"\b_KEY\b", f"{p.name} 가 손잡이 열쇠를 쓴다")
            self.assertNotRegex(_code_only(p), r"\b_tag\(", f"{p.name} 가 손잡이 서명을 만든다")
            self.assertNotRegex(_code_only(p), r"(AccountHandle|ManagerHandle)\(",
                                f"{p.name} 가 손잡이를 직접 만든다 — handles 의 발급 함수만 쓴다")

    def test_personal_fields_not_in_allow_lists(self):
        from naver_engine import fields as F
        every = set(F.CHILD_ACCOUNT) | set(F.MANAGER_ACCOUNT_TOP) | set(F.MANAGER_ACCOUNT_DETAIL) | set(F.CAMPAIGN) \
            | set(F.BIZMONEY) | set(F.CHANNEL) | set(F.STAT_FIELDS)
        for bad in ("ownerNaverId", "naverId", "loginId", "email", "mobilePhone", "phone", "businessInfo",
                    "trackingUrl", "trackingUrlCustomParams", "encryptedSsn", "birthdate", "addr1"):
            self.assertNotIn(bad, every)


if __name__ == "__main__":
    unittest.main()
