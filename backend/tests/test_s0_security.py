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
        self.assertEqual(secret_policy.assess(secret_policy.derive(b"k" * 44, b"label")), "ok")

    def test_reasons_closed(self):
        for v in (None, "xxx", "a" * 5 + "Bc", "ab" * 30, STRONG):
            self.assertIn(secret_policy.assess(v), secret_policy.REASONS)

    def test_other_secret_names(self):
        env = {n: "v-" + n for n in secret_policy.OTHER_SECRET_NAMES}
        self.assertEqual(secret_policy.other_secrets(env), tuple(env[n] for n in secret_policy.OTHER_SECRET_NAMES))
        self.assertNotIn("JWT_SECRET", secret_policy.OTHER_SECRET_NAMES)


class DeriveResolveTest(unittest.TestCase):
    def test_derive_is_stable_and_separated(self):
        a = secret_policy.derive(b"material-1", b"x")
        self.assertEqual(a, secret_policy.derive(b"material-1", b"x"))      # 워커마다 · 다시 떠도 같은 값
        self.assertNotEqual(a, secret_policy.derive(b"material-2", b"x"))
        self.assertNotEqual(a, secret_policy.derive(b"material-1", b"y"))   # 쓰임새마다 다른 값
        self.assertEqual(len(a), 64)
        self.assertEqual(secret_policy.assess(a), "ok")
        for bad in (b"", None):
            with self.assertRaises((ValueError, TypeError)):
                secret_policy.derive(bad, b"x")

    def test_strong_env_is_used(self):
        self.assertEqual(secret_policy.resolve("  " + STRONG + " ", b"m"), (STRONG, "env", "ok"))

    def test_weak_env_never_signs(self):
        derived = secret_policy.derive(b"m", secret_policy.JWT_LABEL)
        for env in (None, "", "please-set-a-strong-secret", "dev-secret-change-me-in-production", "xxx", "short1",
                    "ab" * 40):
            v, src, why = secret_policy.resolve(env, b"m")
            self.assertEqual((v, src), (derived, "derived"), env)
            self.assertNotEqual(why, "ok")

    def test_reused_env_goes_to_derived(self):
        v, src, why = secret_policy.resolve(STRONG, b"m", others=(STRONG,))
        self.assertEqual((src, why), ("derived", "reused"))
        self.assertNotEqual(v, STRONG)

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
            v, _, _ = secret_policy.resolve(weak, b"material")
            secret_policy.resolve(STRONG, b"material")
        finally:
            lg.removeHandler(hd)
        text = "\n".join(cap)
        self.assertEqual(len(cap), 1)                                         # 강한 값은 조용히
        for secret in (weak, v, STRONG, "material"):
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
        for k in ("require_exp", "require_sub", "require_aud", "audience=JWT_AUD"):
            self.assertIn(k, sec)

    def test_written_examples_are_weak(self):
        """저장소에 적힌 ``JWT_SECRET=값`` 모양(예시·기본값)은 모두 쓸 만하지 않다고 판정된다 — 새 예시를 적어도
        서버가 그 값으로 서명하지 않는다(README·HANDOVER 는 열지 않는다)."""
        pat = re.compile(r"JWT_SECRET\s*[=:]\s*[\"']?([^\s\"'}`),]+)")
        found = []
        files = [REPO / "docker-compose.yml", REPO / "DEPLOY.md", REPO / "run.sh"]
        files += [p for p in (BACKEND / "app").rglob("*.py")] + [p for p in (BACKEND / "tools").rglob("*.py")]
        for p in files:
            for m in pat.finditer(p.read_text(encoding="utf-8")):
                v = m.group(1)
                if v.startswith("$") or v in ("", "값"):
                    continue
                found.append((p.name, v))
                self.assertNotEqual(secret_policy.assess(v), "ok", (p.name, v))

    def test_key_files_ignored(self):
        gi = (REPO / ".gitignore").read_text(encoding="utf-8").split()
        for n in ("backend/secret.key", "backend/secret.key.lock", "backend/.init.lock", "data/", ".env"):
            self.assertIn(n, gi)
        di = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
        for n in ("backend/*.key", "backend/*.db", ".env", "data/", "backend/.venv/", ".git"):
            self.assertIn(n, di)


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
        (tmp / "data").mkdir(exist_ok=True)
        env = _env(tmp, env_extra)
        p = subprocess.run([sys.executable, "-W", "ignore", "harness.py", mode], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=timeout)
        line = [ln for ln in p.stdout.split("\n") if ln.startswith("@@RESULT@@")]
        if not line:
            raise AssertionError(f"harness {mode} 실패: {p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-4000:]}")
        return json.loads(line[-1][len("@@RESULT@@"):]), p.stderr, tmp
    finally:
        if own:
            shutil.rmtree(tmp, True)


def _copy_app(tmp):
    shutil.copytree(BACKEND / "app", tmp / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(BACKEND / "static", tmp / "static")
    shutil.copytree(BACKEND / "naver_page", tmp / "naver_page")
    shutil.copy(HARNESS, tmp / "harness.py")
    (tmp / "data").mkdir(exist_ok=True)


def _env(tmp, extra=None):
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update({"DB_PATH": str(tmp / "data" / "t.db"), "FERNET_KEY_FILE": str(tmp / "data" / "k.key"),
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.update(extra or {})
    return env


def _many(tmp, mode, n, extra=None, delay=1.5):
    """같은 폴더에서 파이썬 n 개를 같은 순간(지금+delay 초)에 — 각자 결과 한 줄."""
    import time as _t
    at = str(_t.time() + delay)
    procs = [subprocess.Popen([sys.executable, "-W", "ignore", "harness.py", mode, at], cwd=tmp, env=_env(tmp, extra),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(n)]
    outs = []
    for pr in procs:
        o, e = pr.communicate(timeout=180)
        ln = [x for x in o.split("\n") if x.startswith("@@RESULT@@")]
        outs.append((pr.returncode, json.loads(ln[-1][len("@@RESULT@@"):]) if ln else None, e[-1500:]))
    return outs


@unittest.skipUnless(HAS_APP or REQUIRE_APP, "fastapi·jose 등이 없어 앱 시험을 건너뜀")
class AppTest(unittest.TestCase):
    def test_weak_env_boot(self):
        for weak in ("please-set-a-strong-secret", "", "dev-secret-change-me-in-production"):
            r, err, _ = run_harness("boot", {"JWT_SECRET": weak})
            with self.subTest(weak=weak):
                self.assertEqual(r["source"], "derived")
                self.assertEqual(r["reason"], "missing" if not weak else "known-default")
                self.assertFalse(r["env_used"] and weak)
                self.assertFalse(r["jwt_file"])                            # 서명 값 파일은 따로 두지 않는다
                self.assertEqual(r["key_mode"], 0o600)
                self.assertEqual(r["secret_len"], 64)
                self.assertEqual(r["token_claims"], ["aud", "exp", "role", "sub"])
                t = r["tokens"]
                self.assertEqual((t["login"], t["valid"], t["hand_valid"]), (200, 200, 200))
                for k in ("no_exp", "no_sub", "no_aud", "other_aud", "sub_text", "sub_zero", "sub_int", "sub_neg",
                          "sub_space", "old_default", "code_default", "env_weak", "expired"):
                    self.assertEqual(t[k], 401, k)
                self.assertEqual(r["system_key"]["set"], True)
                self.assertEqual(r["system_key"]["source"], "derived")
                self.assertEqual(set(r["system_key"]) - {"name", "label", "icon", "set", "source", "reason"}, set())
                if weak:
                    self.assertNotIn(weak, err)

    def test_strong_env_boot(self):
        r, err, _ = run_harness("boot", {"JWT_SECRET": STRONG})
        self.assertEqual((r["source"], r["reason"], r["env_used"]), ("env", "ok", True))
        self.assertEqual(r["tokens"]["valid"], 200)
        self.assertEqual(r["tokens"]["env_weak"], 200)            # 강한 환경 값이면 그 값으로 서명한 토큰이 맞다
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
        """파이썬 여덟이 같은 순간에 떠도 서명 값·암호화 키가 하나(해시로만 비교) — 빈 키 파일이 있어도(만들다 멈춘 흔적)."""
        for pre in (None, b""):
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="s0-conv-"))
            try:
                _copy_app(tmp)
                if pre is not None:
                    (tmp / "data" / "k.key").write_bytes(pre)
                outs = _many(tmp, "secret", 8, {"JWT_SECRET": "please-set-a-strong-secret"}, delay=0.0)
                with self.subTest(pre=pre):
                    self.assertEqual([o[0] for o in outs], [0] * 8, [o[2] for o in outs if o[0]])
                    self.assertEqual(len({o[1]["hash"] for o in outs}), 1)
                    self.assertEqual(len({o[1]["fernet"] for o in outs}), 1)
                    self.assertEqual({o[1]["source"] for o in outs}, {"derived"})
                    self.assertEqual(len((tmp / "data" / "k.key").read_bytes()), 44)
            finally:
                shutil.rmtree(tmp, True)

    def test_boot_race(self):
        """워커 여섯이 같은 순간에 app.main 을 불러도(새 DB · 이미 있는 DB) 아무도 죽지 않고 데모 씨앗은 한 번."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="s0-boot-"))
        try:
            _copy_app(tmp)
            for rnd in ("fresh", "existing"):
                outs = _many(tmp, "boot-only", 6, {"JWT_SECRET": ""})
                with self.subTest(rnd=rnd):
                    self.assertEqual([o[0] for o in outs], [0] * 6, [o[2] for o in outs if o[0]])
                    self.assertEqual({o[1]["users"] for o in outs}, {4})
        finally:
            shutil.rmtree(tmp, True)

    def test_fernet_first_creation(self):
        r, _, _ = run_harness("fernet", {"JWT_SECRET": ""})
        self.assertEqual((r["kept"], r["untouched"], r["dead_filled"]), (True, True, True))
        self.assertEqual(r["fresh_len"], 44)
        self.assertEqual((r["fresh_mode"], r["dead_mode"]), (0o600, 0o600))
        self.assertEqual(r["temp_left"], [])

    def test_guard_rules(self):
        r, _, _ = run_harness("guard", {"JWT_SECRET": ""})
        self.assertEqual((r["wait_exact"], r["wait_ids"]), (500, []))
        self.assertEqual(r["after_slide"], [None, 1])
        self.assertEqual((r["old_rows_left"], r["settle_ok_deletes"]), (0, 0))
        self.assertEqual(r["thread_seats"], 10)
        self.assertEqual(r["inflight_same"], [1, 0, False])
        self.assertEqual(r["known_rejected"], [True, 0])
        self.assertEqual(r["no_bucket"], 0)
        self.assertEqual(r["public"], ["8.8.8.8", None, None, None, "2001:4860:4860::", "8.8.4.4"])
        self.assertEqual(r["bucket_names"], [True, True, True])

    def test_reserve_across_processes(self):
        """파이썬 서른이 같은 순간에 한 묶음을 노려도 자리는 정확히 10(워커 넷이 한 줄로 선다)."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="s0-res-"))
        try:
            _copy_app(tmp)
            run_harness("guard", {"JWT_SECRET": ""}, tmp=tmp)        # 키·표 먼저 만들어 둔다
            outs = _many(tmp, "reserve", 30, {"JWT_SECRET": ""}, delay=2.5)
            self.assertEqual([o[0] for o in outs], [0] * 30, [o[2] for o in outs if o[0]])
            self.assertEqual(sum(o[1]["seat"] for o in outs), 10)
        finally:
            shutil.rmtree(tmp, True)

    def test_login_guard(self):
        r, err, _ = run_harness("login", {"JWT_SECRET": ""}, timeout=600)
        self.assertEqual(r["fresh"], {"admin": 200, "lead": 403, "kim": 403, "viewer": 403})
        self.assertEqual(r["rows_after_demo"], 0)                   # 데모 막힘은 실패로 세지 않는다
        self.assertEqual(r["with_other_admin"], 403)
        self.assertEqual(r["other_admin_is_demo"], 200)             # 다른 관리자도 데모 그대로 → 관리자 길을 끊지 않음
        self.assertEqual(r["kim_admin_demo"], 200)
        self.assertEqual((r["kim_changed"], r["admin_after_kim_changed"]), (200, 403))
        self.assertEqual(r["demo_status"], [3, 1])
        self.assertEqual((r["change_to_demo"], r["change_ok"]), (400, 200))
        self.assertEqual(r["acct_fail_codes"], [401] * 10)
        self.assertEqual(r["acct_11th"], 429)
        self.assertTrue(r["acct_retry_after"] and 590 <= int(r["acct_retry_after"]) <= 600, r["acct_retry_after"])
        self.assertEqual(r["acct_case_variant"], 429)
        self.assertEqual(r["other_acct"], 401)
        self.assertEqual((r["acct_after_2min"], r["acct_after_window"]), (429, 200))
        self.assertEqual(r["dummy_verify_calls"], 1)
        self.assertEqual(r["rows_after_success"], 0)
        self.assertEqual((r["far_fail"], r["far_again"], r["near_ok"]), ([401], 429, 200))
        self.assertEqual((r["spread_401"], r["spread_new_ip"]), (100, 429))
        self.assertEqual(r["src_fail"], [401])
        self.assertEqual((r["src_31st"], r["src_other_ip"]), (429, 200))
        self.assertEqual((r["private_fail"], r["cgnat_fail"]), ([401], [401]))
        self.assertEqual((r["private_after"], r["no_header_after"]), (200, 200))
        self.assertFalse(r["buckets_have_email"])
        self.assertFalse(r["buckets_have_private"])
        self.assertEqual((r["burst_401"], r["burst_429"], r["burst_other"]), (10, 50, []))
        self.assertEqual(r["source_rule"], ["8.8.8.8", "1.1.1.1", "1.1.1.1", None, None, None])
        self.assertEqual((r["sso_empty"], r["sso_empty_calls"]), (401, 0))
        self.assertEqual((r["sso_same_token"], r["sso_same_calls"], r["sso_same_rows"]), ([401] * 5, 1, 1))
        self.assertEqual((r["sso_limit"], r["sso_reject"]), (120, [401]))
        self.assertEqual((r["sso_over_blocked"], r["sso_other_ip_ok"], r["password_login_same_ip"]), (429, 200, 200))
        for nm in ("outage503", "garbage", "null_body", "list_body", "str_body", "result_null", "result_list", "no_id",
                   "long_id"):
            self.assertEqual(r["sso_" + nm], [502], nm)
        self.assertEqual((r["rows_after_oddities"], r["sso_conn_error"], r["rows_after_conn_error"]), (0, 502, 0))
        self.assertEqual(r["sso_after"], 200)
        for pw in demo_passwords().values():
            self.assertNotIn(pw, err)
        self.assertIn("데모 계정 로그인 막음", err)
        self.assertLess(err.count("비밀번호 로그인 막음"), 5)        # 막힌 요청마다 줄이 쌓이지 않는다(1분에 한 줄)


if __name__ == "__main__":
    unittest.main()
