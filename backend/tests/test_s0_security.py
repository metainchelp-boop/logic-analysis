"""S0 보안 준비 시험 — 로그인 서명 값 · CORS · 데모 계정 잠금 · 로그인 실패 제한.

앞 절(표준 라이브러리만)은 어디서나 돈다. 뒤 절(``AppTest``)은 진짜 ③ 앱을 임시 폴더에 복사해 따로 띄운 파이썬
(``s0_harness.py``)에서 본다 — fastapi·jose·passlib·cryptography 가 있어야 돈다(없으면 건너뛴 수가 찍힌다 ·
머지·배포 전에는 ``NAVER_RELAY_REQUIRE_APP=1`` 로 건너뛰지 않게).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import cors_policy, secret_policy  # noqa: E402  (표준 라이브러리만)

HAS_APP = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "uvicorn", "sqlalchemy", "jose", "passlib",
                                                     "cryptography"))
REQUIRE_APP = os.environ.get("NAVER_RELAY_REQUIRE_APP") == "1"
HARNESS = pathlib.Path(__file__).resolve().parent / "s0_harness.py"
KEEP_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
STRONG = "s0-" + "Zq8" * 4 + "Lm4Rt7Wx2Yv9Nb3Kc6Hd1Fg5Js0Pa"          # 시험 전용 강한 모양 값(운영 값 아님)


def demo_passwords():
    """seed.py 의 DEMO_PASSWORDS 를 불러오지 않고 읽는다(구문 나무 · 이 값을 시험 파일에 옮겨 적지 않는다)."""
    tree = ast.parse((BACKEND / "app" / "seed.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DEMO_PASSWORDS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("seed.DEMO_PASSWORDS 없음")


# ── 서명 값 판정(순수) ───────────────────────────────────────────────
class AssessTest(unittest.TestCase):
    def test_missing(self):
        for v in (None, "", "   ", "\n", 0, b"x"):
            self.assertEqual(secret_policy.assess(v), "missing", repr(v))

    def test_known_defaults_are_never_ok(self):
        for w in secret_policy.KNOWN_WEAK:
            for v in (w, w.upper(), "  " + w + "\n", w.title()):
                self.assertEqual(secret_policy.assess(v), "known-default", v)

    def test_fragments(self):
        for v in ("please-set-a-strong-secret-2026-prod-long-value", "prod-change-me-in-production-xyz-1234567",
                  "my-dev-secret-for-the-dashboard-9876543210", "this-is-not-a-secret-at-all-000000000000",
                  "example-jwt-key-for-docs-only-000000000000000"):
            self.assertEqual(secret_policy.assess(v), "known-default", v)

    def test_repo_defaults_are_known(self):
        """저장소 어디에든 적혀 있던 기본값 — compose · 코드 · 문서 예시 · 시험 값."""
        for v in ("please-set-a-strong-secret", "dev-secret-change-me-in-production", "xxx",
                  "s12-relay-test-only-not-a-secret"):
            self.assertEqual(secret_policy.assess(v), "known-default", v)

    def test_short_low_variety_reused_ok(self):
        self.assertEqual(secret_policy.assess("a" * 20 + "B7"), "short")
        self.assertEqual(secret_policy.assess("ab" * 30), "low-variety")
        self.assertEqual(secret_policy.assess("0123456789a" * 4), "low-variety")
        self.assertEqual(secret_policy.assess(STRONG, others=("", None, STRONG)), "reused")
        self.assertEqual(secret_policy.assess(STRONG, others=(" " + STRONG + " ",)), "reused")
        self.assertEqual(secret_policy.assess(STRONG, others=("other",)), "ok")
        self.assertEqual(secret_policy.assess(secret_policy.generate()), "ok")

    def test_generated_is_strong_and_fresh(self):
        vals = {secret_policy.generate() for _ in range(50)}
        self.assertEqual(len(vals), 50)
        for v in vals:
            self.assertGreaterEqual(len(v), 64)
            self.assertEqual(secret_policy.assess(v), "ok")

    def test_reasons_closed(self):
        for v in (None, "xxx", "a" * 5 + "Bc", "ab" * 30, STRONG):
            self.assertIn(secret_policy.assess(v), secret_policy.REASONS)

    def test_other_secret_names(self):
        env = {n: "v-" + n for n in secret_policy.OTHER_SECRET_NAMES}
        self.assertEqual(secret_policy.other_secrets(env), tuple(env[n] for n in secret_policy.OTHER_SECRET_NAMES))
        self.assertNotIn("JWT_SECRET", secret_policy.OTHER_SECRET_NAMES)


def _race(args):
    path, = args
    return secret_policy.load_or_create(pathlib.Path(path))[0]


class FileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="s0-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def test_create_once_then_reuse(self):
        p = self.tmp / "sub" / "jwt.key"
        v1, c1 = secret_policy.load_or_create(p)
        v2, c2 = secret_policy.load_or_create(p)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(v1, v2)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(secret_policy.assess(v1), "ok")
        self.assertEqual([x.name for x in p.parent.iterdir() if x.name.startswith(".jwt-")], [])   # 임시 파일 안 남음

    def test_weak_file_is_replaced(self):
        p = self.tmp / "jwt.key"
        for bad in ("please-set-a-strong-secret", "short", "", "ab" * 40):
            p.write_text(bad)
            v, created = secret_policy.load_or_create(p)
            self.assertTrue(created, bad)
            self.assertNotEqual(v, bad)
            self.assertEqual(p.read_text().strip(), v)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_binary_garbage_file_is_replaced(self):
        p = self.tmp / "jwt.key"
        p.write_bytes(b"\xff\xfe\x00bad")
        v, created = secret_policy.load_or_create(p)
        self.assertTrue(created)
        self.assertEqual(secret_policy.assess(v), "ok")

    def test_many_processes_one_value(self):
        """워커 여럿이 동시에 떠도 한 값으로 모인다 — 값이 갈리면 한 워커가 준 토큰을 다른 워커가 거절한다."""
        p = str(self.tmp / "race" / "jwt.key")
        with ProcessPoolExecutor(max_workers=8) as ex:
            vals = list(ex.map(_race, [(p,)] * 24))
        self.assertEqual(len(set(vals)), 1)
        self.assertEqual(pathlib.Path(p).read_text().strip(), vals[0])

    def test_without_lock_first_wins(self):
        old = secret_policy.fcntl
        secret_policy.fcntl = None
        try:
            p = self.tmp / "nolock.key"
            v1, c1 = secret_policy.load_or_create(p)
            v2, c2 = secret_policy.load_or_create(p)
            self.assertEqual((c1, c2, v1 == v2), (True, False, True))
            p.write_text("xxx")
            v3, c3 = secret_policy.load_or_create(p)
            self.assertTrue(c3)
            self.assertNotEqual(v3, "xxx")
        finally:
            secret_policy.fcntl = old


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="s0-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def test_strong_env_is_used_and_no_file(self):
        v, src, why = secret_policy.resolve("  " + STRONG + " ", self.tmp / "jwt.key")
        self.assertEqual((v, src, why), (STRONG, "env", "ok"))
        self.assertFalse((self.tmp / "jwt.key").exists())

    def test_weak_env_never_signs(self):
        for env in (None, "", "please-set-a-strong-secret", "dev-secret-change-me-in-production", "xxx", "short1"):
            v, src, why = secret_policy.resolve(env, self.tmp / "jwt.key")
            self.assertEqual(src, "file", env)
            self.assertNotEqual(v, env)
            self.assertNotIn(v, secret_policy.KNOWN_WEAK)
            self.assertEqual(secret_policy.assess(v), "ok")
            self.assertNotEqual(why, "ok")

    def test_reused_env_goes_to_file(self):
        v, src, why = secret_policy.resolve(STRONG, self.tmp / "jwt.key", others=(STRONG,))
        self.assertEqual((src, why), ("file", "reused"))
        self.assertNotEqual(v, STRONG)

    def test_unwritable_falls_back_to_derived(self):
        blocker = self.tmp / "is-a-file"
        blocker.write_text("x")
        path = blocker / "jwt.key"                 # 부모가 파일이라 만들 수 없다
        v, src, why = secret_policy.resolve("xxx", path, derive_from=b"fernet-key-material")
        v2, _, _ = secret_policy.resolve("xxx", path, derive_from=b"fernet-key-material")
        v3, _, _ = secret_policy.resolve("xxx", path, derive_from=b"other-material")
        self.assertEqual((src, why), ("derived", "known-default"))
        self.assertEqual(v, v2)                    # 워커마다 같은 값
        self.assertNotEqual(v, v3)
        self.assertGreaterEqual(len(v), 64)
        with self.assertRaises(OSError):
            secret_policy.resolve("xxx", path)

    def test_logs_never_carry_values(self):
        cap = []

        class H(logging.Handler):
            def emit(self, rec):
                cap.append(rec.getMessage())

        lg = logging.getLogger("app.secret_policy")
        hd = H()
        lg.addHandler(hd)
        try:
            weak = "please-set-a-strong-secret"
            v, src, why = secret_policy.resolve(weak, self.tmp / "jwt.key")
            blocker = self.tmp / "f"
            blocker.write_text("x")
            v2, _, _ = secret_policy.resolve(weak, blocker / "k", derive_from=b"mat")
        finally:
            lg.removeHandler(hd)
        text = "\n".join(cap)
        self.assertTrue(cap)
        for secret in (weak, v, v2, str(self.tmp)):
            self.assertNotIn(secret, text)
        self.assertIn("known-default", text)


class ComposeTest(unittest.TestCase):
    def test_compose_has_no_default_secret(self):
        """compose 가 약한 기본값을 다시 넣지 않는다 · ${VAR:?} 금지(값이 없으면 compose 명령 전체가 멈춘다)."""
        text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
        m = re.findall(r"JWT_SECRET=\$\{JWT_SECRET:-([^}]*)\}", text)
        self.assertEqual(m, [""])
        self.assertNotRegex(text, r"\$\{[A-Z_]+:\?")
        self.assertNotIn("please-set-a-strong-secret", text)

    def test_code_has_no_default_secret(self):
        sec = (BACKEND / "app" / "security.py").read_text(encoding="utf-8")
        self.assertNotIn("dev-secret-change-me", sec)
        self.assertNotRegex(sec, r'environ\.get\("JWT_SECRET",\s*"')
        self.assertIn("require_exp", sec)
        self.assertIn("require_sub", sec)

    def test_key_files_ignored(self):
        gi = (REPO / ".gitignore").read_text(encoding="utf-8").split()
        for n in ("backend/jwt.key", "backend/jwt.key.lock", "backend/secret.key", "data/"):
            self.assertIn(n, gi)


# ── CORS(순수) ──────────────────────────────────────────────────────
class CorsPolicyTest(unittest.TestCase):
    def test_default_is_closed(self):
        for raw in (None, "", " , ,"):
            self.assertEqual(cors_policy.allowed_origins(raw), ([], 0))

    def test_star_and_bad_shapes_dropped(self):
        for bad in ("*", "null", "https://x/path", "https://x.kr:99999", "https://x.kr:0", "ftp://x.kr",
                    "https://*.metainc.co.kr", "https://x kr", "https://-x.kr", "//x.kr", "https://x.kr?y",
                    "https://user@x.kr", "https://x.kr#a", "javascript:alert(1)"):
            self.assertEqual(cors_policy.allowed_origins(bad), ([], 1), bad)

    def test_exact_origins_kept(self):
        got, dropped = cors_policy.allowed_origins(
            "https://A.metainc.co.kr/, http://x.kr:8080 ,https://a.metainc.co.kr,*")
        self.assertEqual((got, dropped), (["https://a.metainc.co.kr", "http://x.kr:8080"], 1))

    def test_main_has_no_star(self):
        main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
        self.assertNotRegex(main, r'allow_origins\s*=\s*\[\s*"\*"')
        self.assertNotIn('allow_credentials=True', main)
        self.assertIn("allow_origins=_cors_origins", main)


# ── 로그인 지킴(순수 부분 — 앱 없이 부를 수 있는 것만) ─────────────
class GuardPureTest(unittest.TestCase):
    """login_guard 는 모델을 불러오므로 앱 쪽 의존이 있다 — 규칙 함수만 구문 나무·작은 사본으로 본다."""

    def test_demo_passwords_nowhere_else(self):
        """공개된 데모 비밀번호가 seed.py 밖 저장소 파일에 없다(예전 app.js · 시험 도우미에 적혀 있었다).
        README.md · HANDOVER.md 는 열지 않는다(키가 적혀 있는 문서 — 따로 정리 대상)."""
        pw = set(demo_passwords().values())
        files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n")
        hits = []
        for f in files:
            if not f or f in ("README.md", "HANDOVER.md", "backend/app/seed.py"):
                continue
            p = REPO / f
            if not p.is_file() or p.suffix in (".png", ".jpg", ".ico", ".db", ".key"):
                continue
            try:
                t = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(x in t for x in pw):
                hits.append(f)
        self.assertEqual(hits, [])

    def test_seed_does_not_print_passwords(self):
        src = (BACKEND / "app" / "seed.py").read_text(encoding="utf-8")
        pw = demo_passwords().values()
        for line in src.split("\n"):
            if "print(" in line:
                self.assertFalse(any(x in line for x in pw), line)
        self.assertEqual(len(re.findall(r'hash_password\("', src)), 0)

    def test_app_js_gone(self):
        self.assertFalse((BACKEND / "static" / "app.js").exists())
        idx = (BACKEND / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("app.js", idx)


# ── 진짜 앱 ─────────────────────────────────────────────────────────
def run_harness(mode, env_extra=None, tmp=None, timeout=120):
    own = tmp is None
    tmp = tmp or pathlib.Path(tempfile.mkdtemp(prefix="s0-app-"))
    try:
        if not (tmp / "app").exists():
            shutil.copytree(BACKEND / "app", tmp / "app", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(BACKEND / "static", tmp / "static")
            shutil.copytree(BACKEND / "naver_page", tmp / "naver_page")
            shutil.copy(HARNESS, tmp / "harness.py")
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        env.update({"DB_PATH": str(tmp / "t.db"), "FERNET_KEY_FILE": str(tmp / "data" / "k.key"),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        (tmp / "data").mkdir(exist_ok=True)
        env.update(env_extra or {})
        p = subprocess.run([sys.executable, "-W", "ignore", "harness.py", mode], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=timeout)
        line = [ln for ln in p.stdout.split("\n") if ln.startswith("@@RESULT@@")]
        if not line:
            raise AssertionError(f"harness {mode} 실패: {p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-4000:]}")
        return json.loads(line[-1][len("@@RESULT@@"):]), p.stderr, tmp
    finally:
        if own:
            shutil.rmtree(tmp, True)


@unittest.skipUnless(HAS_APP or REQUIRE_APP, "fastapi·jose 등이 없어 앱 시험을 건너뜀")
class AppTest(unittest.TestCase):
    def test_weak_env_boot(self):
        for weak in ("please-set-a-strong-secret", "", "dev-secret-change-me-in-production"):
            r, err, _ = run_harness("boot", {"JWT_SECRET": weak})
            with self.subTest(weak=weak):
                self.assertEqual(r["source"], "file")
                self.assertEqual(r["reason"], "missing" if not weak else "known-default")
                self.assertFalse(r["env_used"] and weak)
                self.assertTrue(r["file_exists"])
                self.assertEqual(r["file_mode"], 0o600)
                self.assertTrue(r["file_matches"])
                self.assertGreaterEqual(r["secret_len"], 64)
                t = r["tokens"]
                self.assertEqual((t["login"], t["valid"]), (200, 200))
                for k in ("no_exp", "no_sub", "sub_text", "sub_zero", "sub_int", "sub_neg", "old_default",
                          "code_default", "env_weak", "expired"):
                    self.assertEqual(t[k], 401, k)
                self.assertEqual(r["system_key"]["set"], True)
                self.assertEqual(r["system_key"]["source"], "file")
                self.assertEqual(set(r["system_key"]) - {"name", "label", "icon", "set", "source", "reason"}, set())
                if weak:
                    self.assertNotIn(weak, err)

    def test_strong_env_boot(self):
        r, err, _ = run_harness("boot", {"JWT_SECRET": STRONG})
        self.assertEqual((r["source"], r["reason"], r["env_used"], r["file_exists"]), ("env", "ok", True, False))
        self.assertEqual(r["tokens"]["valid"], 200)
        self.assertEqual(r["system_key"]["source"], "env")
        self.assertNotIn(STRONG, err)

    def test_cors_closed_by_default(self):
        r, _, _ = run_harness("boot", {"JWT_SECRET": ""})
        for key in ("cors", "cors_same"):
            self.assertIsNone(r[key]["acao"], key)
            self.assertIsNone(r[key]["get_acao"], key)
            self.assertNotEqual(r[key]["status"], 200, key)       # 미리 묻기(preflight)에 「됩니다」를 답하지 않는다
            self.assertEqual(r[key]["get_status"], 200, key)      # 보통 요청은 그대로(화면은 같은 주소)

    def test_cors_allow_list(self):
        r, err, _ = run_harness("cors", {"JWT_SECRET": "", "CORS_ALLOW_ORIGINS": "https://ok.metainc.co.kr,*,null"})
        self.assertEqual(r["origins"], ["https://ok.metainc.co.kr"])
        self.assertEqual(r["dropped"], 2)
        self.assertEqual(r["ok"]["acao"], "https://ok.metainc.co.kr")
        self.assertEqual(r["ok"]["status"], 200)
        self.assertIsNone(r["other"]["acao"])
        self.assertIsNone(r["star"]["acao"])
        self.assertIn("버린 값 2개", err)

    def test_old_files_unused_and_index_ok(self):
        r, _, _ = run_harness("boot", {"JWT_SECRET": ""})
        self.assertEqual(r["app_js"], 404)
        self.assertEqual(r["index"], 200)

    def test_workers_converge(self):
        """같은 폴더에서 파이썬 여섯이 동시에 떠도 서명 값 하나(해시로만 비교)."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="s0-conv-"))
        try:
            shutil.copytree(BACKEND / "app", tmp / "app", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy(HARNESS, tmp / "harness.py")
            (tmp / "data").mkdir()
            env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
            env.update({"DB_PATH": str(tmp / "t.db"), "FERNET_KEY_FILE": str(tmp / "data" / "k.key"),
                        "PYTHONDONTWRITEBYTECODE": "1", "JWT_SECRET": "please-set-a-strong-secret"})
            procs = [subprocess.Popen([sys.executable, "-W", "ignore", "harness.py", "secret"], cwd=tmp, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
            outs = []
            for p in procs:
                o, e = p.communicate(timeout=120)
                ln = [x for x in o.split("\n") if x.startswith("@@RESULT@@")]
                self.assertTrue(ln, e[-2000:])
                outs.append(json.loads(ln[-1][len("@@RESULT@@"):]))
            self.assertEqual(len({o["hash"] for o in outs}), 1)
            self.assertEqual(len({o["fernet"] for o in outs}), 1)
            self.assertEqual({o["source"] for o in outs}, {"file"})
            # 암호화 키도 하나로 모였다(처음 한 번만 만든다)
            self.assertEqual(len([x for x in (tmp / "data").iterdir() if x.name == "k.key"]), 1)
        finally:
            shutil.rmtree(tmp, True)

    def test_fernet_first_creation(self):
        r, _, _ = run_harness("fernet", {"JWT_SECRET": ""})
        self.assertEqual((r["kept"], r["untouched"], r["waited"]), (True, True, True))
        self.assertEqual(r["fresh_len"], 44)
        self.assertEqual(r["fresh_mode"], 0o600)

    def test_login_guard(self):
        r, err, _ = run_harness("login", {"JWT_SECRET": ""}, timeout=300)
        self.assertEqual(r["fresh"], {"admin": 200, "lead": 403, "kim": 403, "viewer": 403})
        self.assertEqual(r["with_other_admin"], 403)
        self.assertEqual(r["other_admin_is_demo"], 200)          # 다른 관리자도 데모 그대로 → 관리자 길을 끊지 않음
        self.assertEqual(r["kim_admin_demo"], 200)
        self.assertEqual((r["kim_changed"], r["admin_after_kim_changed"]), (200, 403))
        self.assertEqual(r["demo_status"], [3, 1])
        self.assertEqual((r["change_to_demo"], r["change_ok"]), (400, 200))
        self.assertEqual(r["acct_fail_codes"], [401] * 10)
        self.assertEqual(r["acct_11th"], 429)
        self.assertTrue(r["acct_retry_after"] and 1 <= int(r["acct_retry_after"]) <= 600)
        self.assertEqual(r["acct_case_variant"], 429)
        self.assertEqual(r["other_acct"], 401)
        self.assertEqual(r["acct_after_2min"], 429)
        self.assertEqual(r["acct_after_window"], 200)
        self.assertEqual(r["dummy_verify_calls"], 1)
        self.assertEqual(r["rows_after_success"], 0)
        self.assertEqual(r["src_fail"], [401])
        self.assertEqual((r["src_31st"], r["src_other_ip"]), (429, 200))
        self.assertEqual(r["private_fail"], [401])
        self.assertEqual((r["private_after"], r["no_header_after"]), (200, 200))
        self.assertFalse(r["buckets_have_email"])
        self.assertEqual(r["sso_reject"], [401])
        self.assertEqual((r["sso_31st_blocked"], r["sso_other_ip_ok"], r["password_login_same_ip"]), (429, 200, 200))
        self.assertEqual(r["sso_outage"], [502])
        self.assertEqual((r["sso_garbage"], r["sso_result_not_dict"]), (502, 401))
        self.assertEqual(r["rows_after_outage"], 1)
        self.assertEqual(r["sso_after_outage"], 200)
        for pw in demo_passwords().values():
            self.assertNotIn(pw, err)
        self.assertIn("데모 계정 로그인 막음", err)


if __name__ == "__main__":
    unittest.main()
