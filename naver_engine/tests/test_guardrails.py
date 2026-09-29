"""구문 시험 — 코드 모양(AST)으로 안전 규칙을 고정한다(설계 v1.8 · 안전 규칙 1·2·11·12).

낱말 찾기가 아니라 코드 구조를 본다(별칭 · 글자 쪼개기 · exec 로 빠져나가지 못하게 — 적대 검토 「시험 충분성」).

- 네트워크를 여는 모듈(urllib · http · socket · ssl · requests …)은 **관문 네 개**(설계 v1.8 M9 · S10 · S11)에서만 import
  한다 — 네이버 관문 ``naver_read.py`` · ① 전산 읽기 관문 ``erp_read.py`` · ① 전산 알림 관문 ``erp_alert.py`` ·
  ① 내 정보 관문 ``erp_profile.py``(관제 화면 로그인 · 직원 본인의 토큰으로만).
- 관문 안에서도 요청을 만드는 곳은 그 관문 ``_gate`` 의 ``Request(`` 한 곳, 보내는 곳은 ``_gate`` 의 ``.send(`` 한 곳이다.
  실제로 여는 곳은 엔진 전체에서 ``UrllibTransport.send`` 의 ``._opener.open(`` 한 곳뿐이다(① 관문도 같은 전송을 쓴다).
  다른 연결 방식(HTTPSConnection 등)은 이름조차 없다.
- 방식 이름으로 쓰이는 글자(대소문자 무관 · 글자 이어 붙이기 포함)는 ``GET`` 뿐이다 — 단 ① 알림 관문 ``erp_alert.py``
  한 곳만 ``POST`` 뿐이다(그 파일에는 ``GET`` 도 없다 · 읽기 관문 셋에는 ``POST`` 가 없다). 관제 화면 API ``web.py`` 는
  **들어오는** 요청의 방식(``GET`` · ``POST``)을 가른다 — 그 파일은 네트워크 모듈을 import 하지 않아 나가는 요청을 만들 수 없다.
- 토큰 비밀값으로 서명하는 ``Secret.mac`` 은 ``session.py`` 한 곳에서만 부른다(S11).
- ③ 쓰기 어댑터·앱 본체를 import 하지 않고, exec · eval · compile · __import__ · importlib · sys.modules · 글자로 된
  getattr 같은 우회도 없다.
- 비밀값은 ``credentials.py`` 밖에서 ``_value`` 로 꺼내지 않고, ``reveal`` 은 관문 ``_gate`` 안에서만 쓴다.
- 손잡이 서명·손잡이 만들기(``_tag`` · ``_KEY`` · ``AccountHandle`` · ``ManagerHandle`` · 미리보기 장부)는 ``handles.py`` 밖에서
  이름조차 쓰지 않는다 — 발급 함수만 쓴다.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ENGINE = pathlib.Path(__file__).resolve().parents[1]
SOURCES = sorted(p for p in ENGINE.rglob("*.py") if "tests" not in p.parts)
# 관문 모듈 → (요청을 만드는 클래스, 관문을 부르는 함수)
GATES = {"naver_read.py": ("NaverReader", "_request"), "erp_read.py": ("ErpReader", "_get"),
         "erp_alert.py": ("ErpAlertPoster", "_post"), "erp_profile.py": ("ErpProfileReader", "_get")}
# 관문 모듈 → 그 관문이 만드는 단 하나의 방식(S10 — 넣기는 ① 알림 관문 하나 · 나머지는 읽기만)
GATE_METHOD = {"naver_read.py": "GET", "erp_read.py": "GET", "erp_alert.py": "POST", "erp_profile.py": "GET"}
# 들어오는 요청을 받는 모듈 → 가르는 방식(S11 관제 화면 API — 네트워크 모듈 import 없음 · 나가는 요청 없음)
INBOUND_METHODS = {"web.py": frozenset({"GET", "POST"})}
NET_MODULES = ("urllib", "http", "socket", "ssl", "requests", "httpx", "aiohttp", "subprocess", "asyncio",
               "ftplib", "smtplib", "telnetlib", "xmlrpc", "multiprocessing")
FORBIDDEN_MODULES = ("app.adapters", "app.main", "app.collector", "app.database", "app.security", "app.models",
                     "naver_searchad", "importlib")
METHOD_WORDS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "CONNECT", "TRACE")
HANDLE_PRIVATE = ("_tag", "_KEY", "_PREVIEW_LEFT", "_PREVIEW_ISSUED", "AccountHandle", "ManagerHandle")
# 저장 — store.py 밖에서는 모듈 이름도, 연결을 만지는 이름도 쓰지 않는다
DB_MODULES = ("sqlite3", "_sqlite3", "dbm", "shelve", "sqlalchemy", "fcntl", "_fcntl", "apsw", "pysqlite2")
DB_ATTRS = ("sqlite3", "_sqlite3", "fcntl", "_fcntl", "_A", "_conn", "_lock_fd", "set_authorizer", "execute",
            "executescript", "executemany", "cursor", "backup", "iterdump", "create_function", "create_aggregate",
            "create_window_function", "create_collation", "enable_load_extension", "load_extension", "setconfig",
            "set_progress_handler", "set_trace_callback", "attrgetter", "methodcaller", "_authorizer", "_tx", "_migrate",
            "_set_meta")
ATTR_FUNCS = ("getattr", "setattr", "hasattr", "delattr")


def _tree(p: pathlib.Path) -> ast.AST:
    return ast.parse(p.read_text(encoding="utf-8"))


def _code_tree(p: pathlib.Path) -> ast.AST:
    """문서 문자열(설명문)을 뺀 코드 — 설명에 적힌 낱말로 시험이 흔들리지 않게."""
    tree = _tree(p)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                body[0] = ast.Pass()
    return tree


def _owners(tree: ast.AST):
    """노드 → (감싸는 클래스 이름, 감싸는 함수 이름)."""
    out = {}

    def visit(node, cls, fn):
        for child in ast.iter_child_nodes(node):
            c = child.name if isinstance(child, ast.ClassDef) else cls
            f = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            out[child] = (c, f)
            visit(child, c, f)
    visit(tree, None, None)
    return out


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node, a.name
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            yield node, base
            for a in node.names:
                yield node, f"{base}.{a.name}"


def _folded_strings(tree: ast.AST):
    """글자 상수와, 상수끼리 이어 붙인 글자(「"PO" + "ST"」 · f"{'PO'}ST")를 모두 꺼낸다."""
    def fold(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a, b = fold(n.left), fold(n.right)
            return a + b if a is not None and b is not None else None
        if isinstance(n, ast.JoinedStr):
            parts = []
            for v in n.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                elif isinstance(v, ast.FormattedValue) and fold(v.value) is not None:
                    parts.append(fold(v.value))
                else:
                    return None
            return "".join(parts)
        return None
    for n in ast.walk(tree):
        s = fold(n)
        if s is not None:
            yield n, s


class GuardrailTest(unittest.TestCase):
    def test_sources_found(self):
        names = {p.name for p in SOURCES}
        self.assertTrue({"naver_read.py", "erp_read.py", "erp_alert.py", "erp_profile.py", "handles.py", "fields.py",
                         "credentials.py", "store.py", "session.py", "views.py", "web.py"} <= names)

    def test_database_only_in_store(self):
        """저장 파일을 여는 곳은 ``store.py`` 한 곳 — 쓰는 곳 하나(대표 결정 D10) · 지우기 거절 연결을 건너뛰지 못하게.

        store 가 import 한 모듈을 다시 꺼내 쓰는 길(``S.sqlite3`` · ``from .store import _sqlite3``)과, 글자로 이름을
        적어 꺼내는 길(``getattr(st, "_conn")``)도 막는다(S6 적대 검토)."""
        for p in SOURCES:
            for node, mod in _imports(_tree(p)):
                parts = mod.lstrip(".").split(".")
                if any(x in DB_MODULES for x in parts):
                    self.assertEqual(p.name, "store.py", f"{p.name}: {mod} — 저장은 store.py 에서만")
            if p.name == "store.py":
                continue
            for n in ast.walk(_tree(p)):
                if isinstance(n, ast.Attribute) and n.attr in DB_ATTRS:
                    self.fail(f"{p.name}: .{n.attr} — 저장 연결은 store.py 밖에서 만지지 않는다")
                if isinstance(n, ast.Name) and n.id in DB_ATTRS:
                    self.fail(f"{p.name}: {n.id} — 저장 연결은 store.py 밖에서 만지지 않는다")
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ATTR_FUNCS:
                    name = n.args[1] if len(n.args) >= 2 else None
                    self.assertIsInstance(name, ast.Constant, f"{p.name}: 글자로 만든 {n.func.id} 금지")
                    self.assertNotIn(name.value, DB_ATTRS, f"{p.name}: {n.func.id}(…, {name.value!r}) — 우회 금지")

    def test_database_guard_catches_bypasses(self):
        """위 시험이 실제로 우회를 잡는지 — 알려진 우회 코드를 넣어 본다."""
        bad = ('from . import store as S\nS.sqlite3.connect("x")\n',
               'from .store import _sqlite3\n',
               'import naver_engine.store\nnaver_engine.store._fcntl\n',
               'def f(st):\n    getattr(st, "_conn").executemany("x", [])\n',
               'def f(st):\n    hasattr(st, "_lock_fd")\n',
               'def f(st, k):\n    getattr(st, k)\n',
               'def f(c):\n    c.cursor()\n',
               'def f(c):\n    c.backup(c)\n',
               'from operator import attrgetter\nattrgetter("_conn")\n')
        for src in bad:
            tree = ast.parse(src)
            hit = False
            for node, mod in _imports(tree):
                if any(x in DB_MODULES for x in mod.lstrip(".").split(".")):
                    hit = True
            for n in ast.walk(tree):
                if isinstance(n, (ast.Attribute, ast.Name)) and (getattr(n, "attr", None) or getattr(n, "id", None)) \
                        in DB_ATTRS:
                    hit = True
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ATTR_FUNCS:
                    name = n.args[1] if len(n.args) >= 2 else None
                    if not isinstance(name, ast.Constant) or name.value in DB_ATTRS:
                        hit = True
            self.assertTrue(hit, src)

    def test_network_modules_only_in_gate_module(self):
        for p in SOURCES:
            if p.name in GATES:
                continue
            for node, mod in _imports(_tree(p)):
                root = mod.lstrip(".").split(".")[0]
                self.assertNotIn(root, NET_MODULES, f"{p.name}: {mod} — 관문 밖 네트워크 금지")

    def test_no_forbidden_imports_or_escape_hatches(self):
        for p in SOURCES:
            tree = _tree(p)
            for node, mod in _imports(tree):
                for bad in FORBIDDEN_MODULES:
                    self.assertNotIn(bad, mod, f"{p.name}: {mod} import 금지")
            for n in ast.walk(tree):
                if isinstance(n, ast.Name):
                    self.assertNotIn(n.id, ("exec", "eval", "compile", "__import__", "globals", "vars"),
                                     f"{p.name}: {n.id} 우회 금지")
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(n.attr, ("modules", "__dict__", "__getattribute__"), f"{p.name}: .{n.attr} 우회 금지")
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("getattr", "setattr", "delattr"):
                    self.assertTrue(len(n.args) >= 2 and isinstance(n.args[1], ast.Constant),
                                    f"{p.name}: 글자로 만든 getattr 금지")
            for _n, s in _folded_strings(_code_tree(p)):
                self.assertNotIn("app.adapters", s, f"{p.name}: 글자로 ③ 어댑터를 가리킴")
                self.assertNotIn("naver_searchad", s, f"{p.name}: 글자로 ③ 어댑터를 가리킴")

    def test_method_words_only_get(self):
        for p in SOURCES:
            want = INBOUND_METHODS.get(p.name) or {GATE_METHOD.get(p.name, "GET")}
            for _n, s in _folded_strings(_code_tree(p)):
                if s.strip().upper() in METHOD_WORDS:
                    self.assertIn(s, want, f"{p.name}: 방식 이름 {s!r}")

    def test_post_only_in_alert_gate(self):
        """나가는 넣기(POST)는 ① 알림 관문 하나 — 그 파일의 방식 글자는 POST 뿐이다. 그 밖에 POST 글자가 있는 곳은 들어오는
        요청을 가르는 화면 API(``web.py``) 하나이고, 그 파일은 관문이 아니며 네트워크 모듈을 import 하지 않는다."""
        seen = {}
        for p in SOURCES:
            for _n, s in _folded_strings(_code_tree(p)):
                if s.strip().upper() in METHOD_WORDS:
                    seen.setdefault(p.name, set()).add(s)
        self.assertEqual(seen.get("erp_alert.py"), {"POST"})
        self.assertEqual({n for n, w in seen.items() if "POST" in w}, {"erp_alert.py"} | set(INBOUND_METHODS))
        for name in INBOUND_METHODS:
            self.assertNotIn(name, GATES)
            for node, mod in _imports(_tree(ENGINE / name)):
                self.assertNotIn(mod.lstrip(".").split(".")[0], NET_MODULES, f"{name}: {mod}")

    def test_profile_gate_borrows_host_from_read_gate(self):
        """내 정보 관문도 호스트·주소를 스스로 적지 않고 읽기 관문의 한 글자를 가져다 쓴다(S11)."""
        tree = _tree(ENGINE / "erp_profile.py")
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        self.assertNotIn(t.id, ("ERP_HOST", "BASE_URL", "ERP_SCHEME", "BASE_HOST"), t.id)
        for _n, s in _folded_strings(_code_tree(ENGINE / "erp_profile.py")):
            self.assertNotIn("metainc.co.kr", s)
            self.assertFalse(s.startswith("http"), "내 정보 관문에 주소 글자가 있다")
        got = set()
        for node, mod in _imports(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "erp_read" and node.level == 1:
                got |= {a.name for a in node.names}
        self.assertTrue({"ERP_HOST", "BASE_URL", "ERP_SCHEME"} <= got)

    def test_token_mac_only_in_session(self):
        """토큰 비밀값 서명(``.mac``)은 ``session.py`` 에서만 — 다른 곳이 비밀값으로 아무 글이나 서명하지 못하게."""
        for p in SOURCES:
            for n in ast.walk(_tree(p)):
                if isinstance(n, ast.Attribute) and n.attr == "mac" and p.name not in ("session.py", "credentials.py"):
                    self.fail(f"{p.name}: .mac 은 session.py 에서만")

    def test_alert_gate_borrows_host_from_read_gate(self):
        """알림 관문은 호스트·주소를 스스로 적지 않고 읽기 관문의 한 글자(``ERP_HOST``)를 가져다 쓴다."""
        tree = _tree(ENGINE / "erp_alert.py")
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        self.assertNotIn(t.id, ("ERP_HOST", "BASE_URL", "ERP_SCHEME", "BASE_HOST"), t.id)
        for _n, s in _folded_strings(_code_tree(ENGINE / "erp_alert.py")):
            self.assertNotIn("metainc.co.kr", s, "알림 관문에 호스트 글자가 있다")
            self.assertFalse(s.startswith("http"), "알림 관문에 주소 글자가 있다")
        got = set()
        for node, mod in _imports(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "erp_read" and node.level == 1:
                got |= {a.name for a in node.names}
        self.assertTrue({"ERP_HOST", "BASE_URL", "ERP_SCHEME"} <= got)

    def test_single_request_path_in_gate_module(self):
        opens = []
        for gate, (cls, caller) in GATES.items():
            tree = _tree(ENGINE / gate)
            owner = _owners(tree)
            seen = {"Request": [], "send": [], "open": []}
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(n.attr, ("HTTPSConnection", "HTTPConnection", "putrequest", "urlopen",
                                              "create_connection", "wrap_socket", "socket"), f"{gate}: 두 번째 요청 길")
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    self.assertNotIn(n.func.attr, ("request", "putrequest", "putheader", "endheaders", "sendall",
                                                   "connect"), f"{gate}: 두 번째 요청 길")
                if isinstance(n, ast.Name):
                    self.assertNotIn(n.id, ("HTTPSConnection", "HTTPConnection", "urlopen", "socket"),
                                     f"{gate}: 두 번째 요청 길")
                if isinstance(n, ast.Call):
                    name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                    if name in seen:
                        seen[name].append(owner.get(n))
            self.assertEqual(seen["Request"], [(cls, "_gate")], f"{gate}: 요청은 관문 한 곳에서만 만든다")
            self.assertEqual(seen["send"], [(cls, "_gate")], f"{gate}: 보내기는 관문에서만")
            opens += [(gate, o) for o in seen["open"]]
            gate_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                          and n.func.attr == "_gate"]
            self.assertTrue(gate_calls, gate)
            for n in gate_calls:
                self.assertIsInstance(n.args[0], ast.Constant, f"{gate}: 관문에는 방식 이름을 글자 그대로 넘긴다")
                self.assertEqual(n.args[0].value, GATE_METHOD[gate])
                self.assertEqual(owner.get(n), (cls, caller), f"{gate}: 관문은 정해진 한 곳에서만 부른다")
        self.assertEqual(opens, [("naver_read.py", ("UrllibTransport", "send"))], "실제로 여는 곳은 엔진 전체에 한 곳")

    def test_gate_hosts_pinned_as_literals(self):
        for gate, const in (("naver_read.py", "BASE_HOST"), ("erp_read.py", "ERP_HOST")):
            tree = _tree(ENGINE / gate)
            vals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == const for t in n.targets)]
            self.assertEqual(len(vals), 1, gate)
            self.assertIsInstance(vals[0], ast.Constant, f"{gate}: 호스트는 글자 그대로")
        self.assertEqual(ast.literal_eval(next(n.value for n in ast.walk(_tree(ENGINE / "erp_read.py"))
                                               if isinstance(n, ast.Assign) and any(
                                                   isinstance(t, ast.Name) and t.id == "ERP_HOST" for t in n.targets))),
                         "api.metainc.co.kr")

    def test_secret_value_only_via_gate(self):
        for p in SOURCES:
            tree = _tree(p)
            owner = _owners(tree)
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and n.attr == "_value" and p.name != "credentials.py":
                    self.fail(f"{p.name}: 비밀값을 _value 로 꺼냄")
                if isinstance(n, ast.Attribute) and n.attr == "reveal" and p.name != "credentials.py":
                    self.assertIn((p.name, owner.get(n)),
                                  {(g, (cls, "_gate")) for g, (cls, _caller) in GATES.items()},
                                  "비밀값은 관문에서만 꺼낸다")

    def test_handle_internals_private(self):
        for p in SOURCES:
            if p.name == "handles.py":
                continue
            tree = _tree(p)
            in_annotation = set()  # 형 표기(주석 성격 · 실행되지 않음)는 뺀다
            for n in ast.walk(tree):
                anns = []
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    anns = [n.returns] + [a.annotation for a in n.args.args + n.args.kwonlyargs + n.args.posonlyargs]
                elif isinstance(n, ast.AnnAssign):
                    anns = [n.annotation]
                for ann in anns:
                    if ann is not None:
                        in_annotation.update(id(x) for x in ast.walk(ann))
            for n in ast.walk(tree):
                if id(n) in in_annotation:
                    continue
                if isinstance(n, ast.Attribute) and n.attr in HANDLE_PRIVATE:
                    self.fail(f"{p.name}: 손잡이 내부 {n.attr} 를 씀 — 발급 함수만 쓴다")
                if isinstance(n, ast.Name) and n.id in HANDLE_PRIVATE:
                    self.fail(f"{p.name}: 손잡이 내부 {n.id} 를 씀")
            for node, mod in _imports(tree):
                self.assertFalse(any(mod.endswith("." + x) for x in HANDLE_PRIVATE), f"{p.name}: {mod}")

    def test_personal_fields_not_in_allow_lists(self):
        from naver_engine import fields as F
        every = set(F.CHILD_ACCOUNT) | set(F.MANAGER_ACCOUNT_TOP) | set(F.MANAGER_ACCOUNT_DETAIL) | set(F.CAMPAIGN) \
            | set(F.BIZMONEY) | set(F.CHANNEL) | set(F.STAT_FIELDS)
        for bad in ("ownerNaverId", "naverId", "loginId", "email", "mobilePhone", "phone", "businessInfo",
                    "trackingUrl", "trackingUrlCustomParams", "encryptedSsn", "birthdate", "addr1"):
            self.assertNotIn(bad, every)


if __name__ == "__main__":
    unittest.main()
