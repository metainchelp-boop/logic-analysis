"""S0 앱 시험 도우미 — ``test_s0_security.py`` 가 **복사한 backend 폴더 안에서** 따로 띄운다(fastapi 필요).

진짜 ``app.main`` 을 불러 본다(운영 DB·파일 무접촉 · 임시 폴더만). 결과는 JSON 한 줄(``@@RESULT@@``)로 표준 출력에.
모드: boot (서명 값 출처·CORS 기본·토큰 규칙) · login (데모 잠금·실패 제한·SSO) · cors (허용 목록) ·
      secret (워커 흉내 — 서명 값·암호화 키 해시) · fernet (암호화 키 첫 생성) · guard (예약 규칙·정리·대기 초) ·
      reserve (한 번 예약하고 결과 — 여러 파이썬이 동시에) · boot-only (app.main 만 불러 보기 — 시작 경합)
찍는 것은 상태 코드·개수·해시뿐 — 비밀번호·서명 값·토큰 원문은 결과에 싣지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import threading
import time
import types

ROOT = os.getcwd()
sys.path.insert(0, ROOT)
_LOCK = []
GLOBAL_A = "8.8.8.8"          # 공인 주소 모양(연결은 하지 않는다 — 머리 값으로만 쓴다)
GLOBAL_B = "1.1.1.1"
PRIVATE = "10.0.0.7"


def _hold_collector_lock():
    import fcntl
    path = os.path.join(os.path.dirname(os.environ["DB_PATH"]), "collector.lock")
    fh = open(path, "w")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _LOCK.append(fh)


def h(v) -> str:
    if isinstance(v, str):
        v = v.encode()
    return hashlib.sha256(v).hexdigest()[:16]


def preflight(c, origin):
    r = c.options("/api/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "content-type"})
    g = c.get("/api/health", headers={"Origin": origin})
    return {"status": r.status_code, "acao": r.headers.get("access-control-allow-origin"),
            "get_acao": g.headers.get("access-control-allow-origin"), "get_status": g.status_code}


def rows(bucket_like=None):
    import sqlite3
    c = sqlite3.connect(os.environ["DB_PATH"])
    try:
        if bucket_like:
            return c.execute("SELECT COUNT(*) FROM login_failures WHERE bucket LIKE ?", (bucket_like,)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        c.close()


def clear():
    import sqlite3
    c = sqlite3.connect(os.environ["DB_PATH"])
    try:
        c.execute("DELETE FROM login_failures")
        c.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        c.close()


def shift(sec):
    import sqlite3
    c = sqlite3.connect(os.environ["DB_PATH"])
    c.execute("UPDATE login_failures SET at = at - ?", (sec,))
    c.commit()
    c.close()


def mode_boot():
    from fastapi.testclient import TestClient
    import app.main as m
    from app import security, seed
    from jose import jwt
    c = TestClient(m.app)
    out = {"source": security.JWT_SOURCE, "reason": security.JWT_REASON,
           "env_used": security.JWT_SECRET == (os.environ.get("JWT_SECRET") or "").strip(),
           "secret_len": len(security.JWT_SECRET), "secret_hash": h(security.JWT_SECRET),
           "jwt_file": os.path.exists(os.path.join(os.path.dirname(os.environ["FERNET_KEY_FILE"]), "jwt.key"))}
    kf = security._KEY_FILE
    out["key_mode"] = stat.S_IMODE(kf.stat().st_mode)
    out["cors"] = preflight(c, "https://evil.example")
    out["cors_same"] = preflight(c, "http://testserver")
    lg = c.post("/api/auth/login", json={"email": "admin@metainc.co.kr",
                                          "password": seed.DEMO_PASSWORDS["admin@metainc.co.kr"]})
    tok = (lg.json() or {}).get("access_token") or ""
    me = lambda t: c.get("/api/auth/me", headers={"Authorization": "Bearer " + t}).status_code
    S, A, AUD = security.JWT_SECRET, security.JWT_ALG, security.JWT_AUD
    import datetime as dt
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    base = {"sub": "1", "exp": exp, "aud": AUD}
    enc = lambda claims, key=S: jwt.encode(claims, key, algorithm=A)
    out["token_claims"] = sorted(jwt.get_unverified_claims(tok)) if tok else []
    out["tokens"] = {
        "login": lg.status_code,
        "valid": me(tok),
        "hand_valid": me(enc(base)),
        "no_exp": me(enc({"sub": "1", "aud": AUD})),
        "no_sub": me(enc({"exp": exp, "aud": AUD})),
        "no_aud": me(enc({"sub": "1", "exp": exp})),
        "other_aud": me(enc({**base, "aud": "logic-analysis"})),
        "sub_text": me(enc({**base, "sub": "abc"})),
        "sub_zero": me(enc({**base, "sub": "0"})),
        "sub_int": me(enc({**base, "sub": 1})),
        "sub_neg": me(enc({**base, "sub": "-1"})),
        "sub_space": me(enc({**base, "sub": " 1"})),
        "old_default": me(enc(base, "please-set-a-strong-secret")),
        "code_default": me(enc(base, "dev-secret-change-me-in-production")),
        "env_weak": me(enc(base, os.environ.get("JWT_SECRET") or "x")),
        "expired": me(enc({**base, "exp": exp - dt.timedelta(hours=2)})),
    }
    keys = c.get("/api/admin/system-keys", headers={"Authorization": "Bearer " + tok}).json()
    row = [k for k in keys.get("keys", []) if k.get("name") == "JWT_SECRET"]
    out["system_key"] = row[0] if row else None
    out["app_js"] = c.get("/app.js").status_code
    out["index"] = c.get("/").status_code
    return out


class _Resp:
    def __init__(self, status, body=None, text=None):
        self.status_code = status
        self._body = body
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._body


def mode_login():
    from fastapi.testclient import TestClient
    import app.main as m
    from app import models, security, seed, login_guard
    from app.database import SessionLocal
    from app.routers import auth as auth_router
    import requests
    c = TestClient(m.app)
    D = seed.DEMO_PASSWORDS
    out = {}

    def login(email, pw, ip=None, client=None):
        hd = {"X-Real-IP": ip} if ip else {}
        r = (client or c).post("/api/auth/login", json={"email": email, "password": pw}, headers=hd)
        return r.status_code

    # ① 데모 잠금 — 처음 설치 상태(관리자는 데모 관리자뿐) · 막힘(403)은 실패로 세지 않는다
    out["fresh"] = {e.split("@")[0]: login(e, pw) for e, pw in D.items()}
    out["rows_after_demo"] = rows()
    # ② 다른 관리자(전산 SSO 계정 모양)가 생기면 데모 관리자도 막힌다
    db = SessionLocal()
    other = models.User(email="erp:s0-other-admin", name="다른 관리자", role="admin",
                        password_hash=security.hash_password("s0-random-" + "q" * 20))
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    out["with_other_admin"] = login("admin@metainc.co.kr", D["admin@metainc.co.kr"])
    # ③ 다른 관리자가 데모 비밀번호 그대로인 데모 계정이면 셈에서 빠진다
    db = SessionLocal()
    db.query(models.User).filter(models.User.id == other_id).delete()
    kim = db.query(models.User).filter(models.User.email == "kim@metainc.co.kr").first()
    kim.role = "admin"
    db.commit()
    db.close()
    out["other_admin_is_demo"] = login("admin@metainc.co.kr", D["admin@metainc.co.kr"])
    out["kim_admin_demo"] = login("kim@metainc.co.kr", D["kim@metainc.co.kr"])
    # ④ 비밀번호를 바꾼 데모 계정은 그대로 쓴다 — 그러면 데모 관리자는 막힌다
    good = "s0-changed-" + "k" * 12
    db = SessionLocal()
    kim = db.query(models.User).filter(models.User.email == "kim@metainc.co.kr").first()
    kim.password_hash = security.hash_password(good)
    db.commit()
    db.close()
    out["kim_changed"] = login("kim@metainc.co.kr", good)
    out["admin_after_kim_changed"] = login("admin@metainc.co.kr", D["admin@metainc.co.kr"])
    db = SessionLocal()
    out["demo_status"] = list(login_guard.demo_status(db))
    db.close()

    # ⑤ 공개된 데모 비밀번호로는 바꿀 수 없다
    tok = c.post("/api/auth/login", json={"email": "kim@metainc.co.kr", "password": good}).json()["access_token"]
    auth = {"Authorization": "Bearer " + tok}
    out["change_to_demo"] = c.post("/api/auth/change-password", headers=auth, json={
        "current_password": good, "new_password": D["viewer@metainc.co.kr"]}).status_code
    nxt = "s0-next-" + "n" * 12
    out["change_ok"] = c.post("/api/auth/change-password", headers=auth, json={
        "current_password": good, "new_password": nxt}).status_code
    good = nxt

    # ⑥ 곳 모름(머리 없음) — 계정 10번 → 11번째는 맞는 비밀번호여도 429 · 다른 계정은 그대로 · 대소문자만 바꿔도 같은 묶음
    clear()
    out["acct_fail_codes"] = [login("kim@metainc.co.kr", "wrong-%d" % i) for i in range(10)]
    r = c.post("/api/auth/login", json={"email": "kim@metainc.co.kr", "password": good})
    out["acct_11th"] = r.status_code
    out["acct_retry_after"] = r.headers.get("retry-after")
    out["acct_case_variant"] = login("KIM@metainc.co.kr", good)
    out["other_acct"] = login("lead@metainc.co.kr", "wrong")
    shift(120)
    out["acct_after_2min"] = login("kim@metainc.co.kr", good)
    shift(540)
    out["acct_after_window"] = login("kim@metainc.co.kr", good)
    # 없는 이메일도 비밀번호 확인을 한 번 한다
    calls = []
    real_verify = security.verify_password
    security.verify_password = lambda p, hsh: calls.append(1) or real_verify(p, hsh)
    try:
        login("s0-no-such@x.kr", "whatever")
    finally:
        security.verify_password = real_verify
    out["dummy_verify_calls"] = len(calls)
    # 맞는 로그인은 세지 않는다(먼저 적은 줄을 지운다)
    clear()
    for _ in range(15):
        login("kim@metainc.co.kr", good, ip=GLOBAL_A)
    out["rows_after_success"] = rows()

    # ⑦ 계정 × 곳 — 먼 곳 A 에서 10번 틀려도 곳 B 의 그 사람은 들어간다(남이 관리자를 잠그지 못하게)
    clear()
    out["far_fail"] = sorted(set(login("kim@metainc.co.kr", "w%d" % i, ip=GLOBAL_A) for i in range(10)))
    out["far_again"] = login("kim@metainc.co.kr", good, ip=GLOBAL_A)
    out["near_ok"] = login("kim@metainc.co.kr", good, ip=GLOBAL_B)
    # 한 계정 전체 100번 — 곳 11개를 돌려 가며 110번 틀리면 새 곳에서도 막힌다
    clear()
    ips = ["8.8.4.%d" % i for i in range(1, 12)]
    codes = [login("kim@metainc.co.kr", "w", ip=ip) for ip in ips for _ in range(10)]
    out["spread_401"] = codes.count(401)
    out["spread_new_ip"] = login("kim@metainc.co.kr", good, ip="9.9.9.9")
    # 한 곳 30번 — 계정을 바꿔 가며
    clear()
    out["src_fail"] = sorted(set(login("nobody%d@x.kr" % i, "w", ip=GLOBAL_A) for i in range(30)))
    out["src_31st"] = login("kim@metainc.co.kr", good, ip=GLOBAL_A)
    out["src_other_ip"] = login("kim@metainc.co.kr", good, ip=GLOBAL_B)
    # 내부 주소 · 통신사 공용 대역은 곳으로 세지 않는다
    clear()
    out["private_fail"] = sorted(set(login("nobody%d@x.kr" % i, "w", ip=PRIVATE) for i in range(35)))
    out["cgnat_fail"] = sorted(set(login("nobody%d@y.kr" % i, "w", ip="100.64.1.9") for i in range(35)))
    out["private_after"] = login("kim@metainc.co.kr", good, ip=PRIVATE)
    out["no_header_after"] = login("kim@metainc.co.kr", good)
    import sqlite3
    cc = sqlite3.connect(os.environ["DB_PATH"])
    buckets = [b for (b,) in cc.execute("SELECT bucket FROM login_failures")]
    cc.close()
    out["buckets_have_email"] = any("@" in b or "nobody" in b or "kim" in b for b in buckets)
    out["buckets_have_private"] = any(PRIVATE in b or "100.64" in b for b in buckets)

    # ⑧ 동시에 몰아 보내도 상한을 넘지 못한다 — 60개 동시 · 한 계정 · 한 곳
    clear()
    res = []
    lock = threading.Lock()

    def burst(i):
        cl = TestClient(m.app)
        s = login("kim@metainc.co.kr", "burst-%d" % i, ip=GLOBAL_A, client=cl)
        with lock:
            res.append(s)
    ts = [threading.Thread(target=burst, args=(i,)) for i in range(60)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    out["burst_401"] = res.count(401)
    out["burst_429"] = res.count(429)
    out["burst_other"] = sorted(set(res) - {401, 429})

    # ⑨ 「곳」 규칙 — 머리 먼저 · 없으면 연결 주소(인자 순서 바꾸면 틀린다)
    fr = lambda hd, peer: auth_router._source(types.SimpleNamespace(
        headers=hd, client=types.SimpleNamespace(host=peer) if peer else None))
    out["source_rule"] = [fr({"x-real-ip": GLOBAL_A}, GLOBAL_B), fr({}, GLOBAL_B), fr({"x-real-ip": "모양틀림"}, GLOBAL_B),
                          fr({"x-real-ip": PRIVATE}, GLOBAL_B), fr({}, None), fr({"x-real-ip": "100.64.0.5"}, None)]

    # ⑩ SSO — ① 이 거절한 서로 다른 토큰만 센다 · 같은 토큰 다시 = ① 에 안 묻고 401 · 빈 토큰·① 장애·이상한 답은 안 셈
    clear()
    real_get = requests.get
    erp_calls = []

    def fake(status, body=None, text=None):
        def g(*a, **k):
            erp_calls.append(1)
            return _Resp(status, body, text)
        return g
    sso = lambda tokn, ip=GLOBAL_A: c.post("/api/auth/sso", json={"token": tokn}, headers={"X-Real-IP": ip}).status_code
    ok_body = {"result": {"id": "s0user", "name": "시험", "teamList": []}}
    try:
        requests.get = fake(401, {})
        out["sso_empty"] = sso("   ")
        out["sso_empty_calls"] = len(erp_calls)
        out["sso_same_token"] = [sso("same-stale") for _ in range(5)]
        out["sso_same_calls"] = len(erp_calls)
        out["sso_same_rows"] = rows("sso-src:%")
        clear()
        erp_calls.clear()
        out["sso_limit"] = login_guard.SSO_SOURCE_MAX
        out["sso_reject"] = sorted(set(sso("t%d" % i) for i in range(120)))     # 상한 120 을 글자로(상수를 바꿔도 시험이 따라가지 않게)
        requests.get = fake(200, ok_body)
        out["sso_over_blocked"] = sso("fresh-good")
        out["sso_other_ip_ok"] = sso("fresh-good", ip=GLOBAL_B)
        out["password_login_same_ip"] = login("kim@metainc.co.kr", good, ip=GLOBAL_A)
        clear()
        for nm, (st, bd, tx) in {"outage503": (503, {}, None), "garbage": (200, None, "<html>"),
                                  "null_body": (200, None, None), "list_body": (200, [], None),
                                  "str_body": (200, "x", None), "result_null": (200, {"result": None}, None),
                                  "result_list": (200, {"result": []}, None),
                                  "no_id": (200, {"result": {"id": ""}}, None),
                                  "long_id": (200, {"result": {"id": "x" * 101}}, None)}.items():
            requests.get = fake(st, bd, tx)
            out["sso_" + nm] = sorted(set(sso("o-" + nm + str(i)) for i in range(3)))
        out["rows_after_oddities"] = rows()

        def boom(*a, **k):
            raise OSError("no route")
        requests.get = boom
        out["sso_conn_error"] = sso("conn")
        out["rows_after_conn_error"] = rows()
        requests.get = fake(200, ok_body)
        out["sso_after"] = sso("ok-after")
    finally:
        requests.get = real_get
    return out


def mode_cors():
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    return {"ok": preflight(c, "https://ok.metainc.co.kr"), "other": preflight(c, "https://evil.example"),
            "star": preflight(c, "*"), "origins": list(m._cors_origins), "dropped": m._cors_dropped}


def _wait_until(at: float):
    while time.time() < at:
        time.sleep(0.0005)


def mode_secret():
    """워커 여럿 흉내 — 같은 폴더에서 이 파이썬들이 **같은 순간에** app.security 를 불러 같은 값을 쓰는가(해시만).
    무거운 부품을 먼저 불러 두고 시작 시각까지 기다린다 — 그래야 키 파일을 두고 실제로 겨룬다(처음 판은 파이썬마다
    부품 불러오는 시간이 달라 한 줄로 서 버려, 잠금을 빼도 시험이 통과했다 · 방해 시험)."""
    import cryptography.fernet  # noqa: F401
    import jose.jwt  # noqa: F401
    import passlib.context  # noqa: F401
    import app.secret_policy  # noqa: F401
    if len(sys.argv) > 2:
        _wait_until(float(sys.argv[2]))
    from app import security
    f = security._fernet
    return {"hash": h(security.JWT_SECRET), "source": security.JWT_SOURCE, "reason": security.JWT_REASON,
            "fernet": h(f._signing_key + f._encryption_key)}


def mode_fernet():
    """암호화 키 첫 생성 — 이미 누가 만든 파일이 있으면 그 키 · 빈 파일(만들다 멈춘 흔적)은 새로 채운다 · 권한 600."""
    import pathlib
    from app import security
    d = pathlib.Path(os.environ["FERNET_KEY_FILE"]).parent
    win = d / "winner.key"
    win.write_bytes(b"WINNERKEY")
    got = security._create_key_once(win)
    dead = d / "dead.key"
    dead.write_bytes(b"")
    got2 = security._create_key_once(dead)
    fresh = d / "fresh.key"
    got3 = security._create_key_once(fresh)
    left = sorted(x.name for x in d.iterdir() if x.name.startswith(".key-"))
    return {"kept": got == b"WINNERKEY", "untouched": win.read_bytes() == b"WINNERKEY",
            "dead_filled": len(got2) == 44 and dead.read_bytes() == got2,
            "fresh_len": len(got3), "fresh_mode": stat.S_IMODE(fresh.stat().st_mode),
            "dead_mode": stat.S_IMODE(dead.stat().st_mode), "temp_left": left}


def mode_guard():
    """예약 규칙 — 대기 초가 정확한가 · 한 시간 지난 줄 정리 · 같은 파이썬 스레드 50개 동시 예약."""
    from app import login_guard as g
    out = {}
    b = "acct-local:guardtest"
    for i in range(10):
        t = g.reserve([b], now=1000.0 + i)
        g.settle(t, failed=True)
    t = g.reserve([b], now=1100.0)
    out["wait_exact"] = t.wait                    # 가장 오래된 1000 이 벗어나는 때 = 1000+600-1100 = 500
    out["wait_ids"] = t.ids
    t2 = g.reserve([b], now=1601.0)               # 1000 이 벗어났다 → 자리 하나
    out["after_slide"] = (t2.wait, len(t2.ids))
    g.settle(t2, failed=True)
    import sqlite3
    c = sqlite3.connect(os.environ["DB_PATH"])
    t3 = g.reserve(["acct-local:other"], now=1601.0 + g.KEEP + 10)   # 한 시간 넘게 지난 줄은 지운다
    g.settle(t3, failed=False)
    out["old_rows_left"] = c.execute("SELECT COUNT(*) FROM login_failures WHERE at < ?", (1700.0,)).fetchone()[0]
    out["settle_ok_deletes"] = c.execute("SELECT COUNT(*) FROM login_failures WHERE bucket='acct-local:other'").fetchone()[0]
    c.close()
    # 스레드 50개 동시 — 자리는 정확히 10
    got = []
    lk = threading.Lock()
    start = threading.Event()

    def one():
        start.wait()
        tk = g.reserve(["acct-local:thread"])
        with lk:
            got.append(bool(tk.ids))
    ts = [threading.Thread(target=one) for _ in range(50)]
    [t.start() for t in ts]
    start.set()
    [t.join() for t in ts]
    out["thread_seats"] = got.count(True)
    # SSO 거절 캐시 — 거절된 토큰은 다시 묻지 않는다 · 확인 중인 같은 토큰은 새로 세지 않는다
    s = "sso-src:8.8.8.8"
    a = g.reserve([s], tag="tA", now=5000.0)
    b2 = g.reserve([s], tag="tA", now=5000.5)
    out["inflight_same"] = (len(a.ids), len(b2.ids), b2.known_rejected)
    g.settle(a, failed=True)
    c3 = g.reserve([s], tag="tA", now=5001.0)
    out["known_rejected"] = (c3.known_rejected, len(c3.ids))
    # 묶음이 없으면(곳 모름 SSO) 아무것도 적지 않는다
    out["no_bucket"] = len(g.reserve([], tag="x").ids)
    # 곳 규칙
    out["public"] = [g.public_source("8.8.8.8", None), g.public_source("100.64.1.1", None),
                     g.public_source("10.0.0.1", None), g.public_source("::1", None),
                     g.public_source("2001:4860:4860::8888", None), g.public_source(None, "8.8.4.4")]
    # 묶음 이름에 원문 없음 · 서버 키로 뽑음(같은 이메일 = 같은 이름 · 대소문자 무시)
    out["bucket_names"] = [g.account_key("A@b.kr") == g.account_key(" a@B.KR "),
                           "a@b.kr" not in g.account_key("a@b.kr"),
                           g.account_key("a@b.kr") != hashlib.sha256(b"acct:a@b.kr").hexdigest()[:32]]
    return out


def mode_reserve():
    """여러 파이썬이 동시에 — 시작 시각까지 기다렸다가 한 번 예약하고 자리를 얻었는지만 찍는다."""
    from app import login_guard as g
    _wait_until(float(sys.argv[2]))
    t = g.reserve(["acct-local:procs"])
    return {"seat": bool(t.ids)}


def mode_boot_only():
    """app.main 만 불러 본다 — 여러 파이썬이 같은 순간에(시작 경합 · 표 만들기 · 데모 씨앗)."""
    import fastapi  # noqa: F401  — 무거운 부품·라우터를 먼저(같은 순간에 표 만들기·씨앗으로 겨루게)
    import sqlalchemy  # noqa: F401
    import app.database  # noqa: F401
    import app.models  # noqa: F401
    import app.security  # noqa: F401
    import app.seed  # noqa: F401
    import app.cors_policy  # noqa: F401
    from app.routers import auth, clients, insights, erp, naver  # noqa: F401
    _wait_until(float(sys.argv[2]))
    import app.main  # noqa: F401
    from app import models
    from app.database import SessionLocal
    db = SessionLocal()
    n = db.query(models.User).count()
    db.close()
    return {"ok": True, "users": n}


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode in ("boot", "login", "cors"):
        _hold_collector_lock()
    res = {"boot": mode_boot, "login": mode_login, "cors": mode_cors, "secret": mode_secret,
           "fernet": mode_fernet, "guard": mode_guard, "reserve": mode_reserve,
           "boot-only": mode_boot_only}[mode]()
    print("@@RESULT@@" + json.dumps(res, ensure_ascii=True))
