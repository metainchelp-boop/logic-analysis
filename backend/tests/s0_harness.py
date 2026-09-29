"""S0 앱 시험 도우미 — ``test_s0_security.py`` 가 **복사한 backend 폴더 안에서** 따로 띄운다(fastapi 필요).

진짜 ``app.main`` 을 불러 본다(운영 DB·파일 무접촉 · 임시 폴더만). 결과는 JSON 한 줄(``@@RESULT@@``)로 표준 출력에.
모드: boot (서명 값 출처·파일·CORS 기본·토큰 규칙) · login (데모 잠금·실패 제한·SSO) · cors (허용 목록을 준 경우)
찍는 것은 상태 코드·개수·해시뿐 — 비밀번호·서명 값·토큰 원문은 결과에 싣지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys

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


def h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:16]


def preflight(c, origin):
    r = c.options("/api/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "content-type"})
    g = c.get("/api/health", headers={"Origin": origin})
    return {"status": r.status_code, "acao": r.headers.get("access-control-allow-origin"),
            "get_acao": g.headers.get("access-control-allow-origin"), "get_status": g.status_code}


def mode_boot():
    from fastapi.testclient import TestClient
    import app.main as m
    from app import security
    from jose import jwt
    c = TestClient(m.app)
    out = {"source": security.JWT_SOURCE, "reason": security.JWT_REASON,
           "env_used": security.JWT_SECRET == (os.environ.get("JWT_SECRET") or "").strip(),
           "secret_len": len(security.JWT_SECRET), "secret_hash": h(security.JWT_SECRET)}
    f = security.JWT_SECRET_FILE
    out["file_exists"] = f.exists()
    out["file_mode"] = stat.S_IMODE(f.stat().st_mode) if f.exists() else None
    out["file_matches"] = f.exists() and f.read_text().strip() == security.JWT_SECRET
    out["cors"] = preflight(c, "https://evil.example")
    out["cors_same"] = preflight(c, "http://testserver")
    # 토큰 규칙 — 로그인해서 받은 토큰 · exp 없음 · sub 없음 · 숫자 아닌 sub · 0 · 다른 값으로 서명
    from app import seed
    lg = c.post("/api/auth/login", json={"email": "admin@metainc.co.kr",
                                          "password": seed.DEMO_PASSWORDS["admin@metainc.co.kr"]})
    tok = (lg.json() or {}).get("access_token") or ""
    me = lambda t: c.get("/api/auth/me", headers={"Authorization": "Bearer " + t}).status_code
    S, A = security.JWT_SECRET, security.JWT_ALG
    import datetime as dt
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    out["tokens"] = {
        "login": lg.status_code,
        "valid": me(tok),
        "no_exp": me(jwt.encode({"sub": "1", "role": "admin"}, S, algorithm=A)),
        "no_sub": me(jwt.encode({"role": "admin", "exp": exp}, S, algorithm=A)),
        "sub_text": me(jwt.encode({"sub": "abc", "exp": exp}, S, algorithm=A)),
        "sub_zero": me(jwt.encode({"sub": "0", "exp": exp}, S, algorithm=A)),
        "sub_int": me(jwt.encode({"sub": 1, "exp": exp}, S, algorithm=A)),
        "sub_neg": me(jwt.encode({"sub": "-1", "exp": exp}, S, algorithm=A)),
        "old_default": me(jwt.encode({"sub": "1", "exp": exp}, "please-set-a-strong-secret", algorithm=A)),
        "code_default": me(jwt.encode({"sub": "1", "exp": exp}, "dev-secret-change-me-in-production", algorithm=A)),
        "env_weak": me(jwt.encode({"sub": "1", "exp": exp}, os.environ.get("JWT_SECRET") or "x", algorithm=A)),
        "expired": me(jwt.encode({"sub": "1", "exp": exp - dt.timedelta(hours=2)}, S, algorithm=A)),
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
    import requests
    c = TestClient(m.app)
    D = seed.DEMO_PASSWORDS
    out = {}

    def login(email, pw, ip=None):
        hd = {"X-Real-IP": ip} if ip else {}
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers=hd)
        return r.status_code

    def clear():
        db = SessionLocal()
        db.query(models.LoginFailure).delete()
        db.commit()
        db.close()

    # ① 데모 잠금 — 처음 설치 상태(관리자는 데모 관리자뿐)
    out["fresh"] = {e.split("@")[0]: login(e, pw) for e, pw in D.items()}
    # ② 다른 관리자(전산 SSO 계정 모양)가 생기면 데모 관리자도 막힌다
    db = SessionLocal()
    other = models.User(email="erp:s0-other-admin", name="다른 관리자", role="admin",
                        password_hash=security.hash_password("s0-random-" + "q" * 20))
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    out["with_other_admin"] = login("admin@metainc.co.kr", D["admin@metainc.co.kr"])
    # ③ 다른 관리자가 있어도 그 관리자가 데모 비밀번호 그대로인 데모 계정이면 셈에서 빠진다
    db = SessionLocal()
    db.query(models.User).filter(models.User.id == other_id).delete()
    kim = db.query(models.User).filter(models.User.email == "kim@metainc.co.kr").first()
    kim.role = "admin"
    db.commit()
    db.close()
    out["other_admin_is_demo"] = login("admin@metainc.co.kr", D["admin@metainc.co.kr"])
    out["kim_admin_demo"] = login("kim@metainc.co.kr", D["kim@metainc.co.kr"])
    # ④ 비밀번호를 바꾼 데모 계정은 그대로 쓴다 — 그러면 데모 관리자는 막힌다(쓸 수 있는 다른 관리자가 생김)
    db = SessionLocal()
    kim = db.query(models.User).filter(models.User.email == "kim@metainc.co.kr").first()
    kim.password_hash = security.hash_password("s0-changed-" + "k" * 12)
    db.commit()
    db.close()
    out["kim_changed"] = login("kim@metainc.co.kr", "s0-changed-" + "k" * 12)
    out["admin_after_kim_changed"] = login("admin@metainc.co.kr", D["admin@metainc.co.kr"])
    db = SessionLocal()
    out["demo_status"] = list(login_guard.demo_status(db))
    db.close()

    # ⑤ 공개된 데모 비밀번호로는 바꿀 수 없다
    tok = c.post("/api/auth/login", json={"email": "kim@metainc.co.kr", "password": "s0-changed-" + "k" * 12}).json()["access_token"]
    auth = {"Authorization": "Bearer " + tok}
    out["change_to_demo"] = c.post("/api/auth/change-password", headers=auth, json={
        "current_password": "s0-changed-" + "k" * 12, "new_password": D["viewer@metainc.co.kr"]}).status_code
    out["change_ok"] = c.post("/api/auth/change-password", headers=auth, json={
        "current_password": "s0-changed-" + "k" * 12, "new_password": "s0-next-" + "n" * 12}).status_code

    # ⑥ 계정 실패 10번 → 11번째는 맞는 비밀번호여도 429 · 다른 계정은 그대로
    clear()
    good = "s0-next-" + "n" * 12
    out["acct_fail_codes"] = [login("kim@metainc.co.kr", "wrong-%d" % i) for i in range(10)]
    r = c.post("/api/auth/login", json={"email": "kim@metainc.co.kr", "password": good})
    out["acct_11th"] = r.status_code
    out["acct_retry_after"] = r.headers.get("retry-after")
    out["acct_case_variant"] = login("KIM@metainc.co.kr", good)     # 대소문자만 바꿔도 같은 묶음
    out["other_acct"] = login("lead@metainc.co.kr", "wrong")

    def shift(sec):
        db = SessionLocal()
        for row in db.query(models.LoginFailure).all():
            row.at -= sec
        db.commit()
        db.close()
    # 2분 지나도 아직 창 안 — 막힘 그대로 · 11분이면 풀린다
    shift(120)
    out["acct_after_2min"] = login("kim@metainc.co.kr", good)
    shift(540)
    out["acct_after_window"] = login("kim@metainc.co.kr", good)
    # 없는 이메일도 비밀번호 확인을 한 번 한다(시간으로 있는 계정을 알아내지 못하게)
    calls = []
    real_verify = security.verify_password
    security.verify_password = lambda p, hsh: calls.append(1) or real_verify(p, hsh)
    try:
        login("s0-no-such@x.kr", "whatever")
    finally:
        security.verify_password = real_verify
    out["dummy_verify_calls"] = len(calls)
    # 맞는 로그인은 세지 않는다
    clear()
    for _ in range(15):
        login("kim@metainc.co.kr", good)
    db = SessionLocal()
    out["rows_after_success"] = db.query(models.LoginFailure).count()
    db.close()

    # ⑦ 한 곳(공인 주소) 30번 → 31번째는 새 계정이어도 429 · 내부 주소는 곳으로 세지 않는다 · 다른 공인 주소는 그대로
    clear()
    out["src_fail"] = sorted(set(login("nobody%d@x.kr" % i, "w", ip=GLOBAL_A) for i in range(30)))
    out["src_31st"] = login("kim@metainc.co.kr", good, ip=GLOBAL_A)
    out["src_other_ip"] = login("kim@metainc.co.kr", good, ip=GLOBAL_B)
    clear()
    out["private_fail"] = sorted(set(login("nobody%d@x.kr" % i, "w", ip=PRIVATE) for i in range(35)))
    out["private_after"] = login("kim@metainc.co.kr", good, ip=PRIVATE)
    out["no_header_after"] = login("kim@metainc.co.kr", good)
    db = SessionLocal()
    out["buckets_have_email"] = any("@" in b or "nobody" in b for (b,) in db.query(models.LoginFailure.bucket).all())
    db.close()

    # ⑧ SSO — ① 이 거절한 것만 센다 · ① 장애(502)는 세지 않는다
    clear()
    real_get = requests.get
    try:
        requests.get = lambda *a, **k: _Resp(401, {})
        out["sso_reject"] = sorted(set(c.post("/api/auth/sso", json={"token": "t%d" % i},
                                              headers={"X-Real-IP": GLOBAL_A}).status_code for i in range(30)))
        requests.get = lambda *a, **k: _Resp(200, {"result": {"id": "s0user", "name": "시험", "teamList": []}})
        out["sso_31st_blocked"] = c.post("/api/auth/sso", json={"token": "ok"}, headers={"X-Real-IP": GLOBAL_A}).status_code
        out["sso_other_ip_ok"] = c.post("/api/auth/sso", json={"token": "ok"}, headers={"X-Real-IP": GLOBAL_B}).status_code
        out["password_login_same_ip"] = login("kim@metainc.co.kr", good, ip=GLOBAL_A)
        clear()
        requests.get = lambda *a, **k: _Resp(503, {})
        out["sso_outage"] = sorted(set(c.post("/api/auth/sso", json={"token": "t"},
                                              headers={"X-Real-IP": GLOBAL_A}).status_code for _ in range(35)))
        requests.get = lambda *a, **k: _Resp(200, None, text="<html>")
        out["sso_garbage"] = c.post("/api/auth/sso", json={"token": "t"}, headers={"X-Real-IP": GLOBAL_A}).status_code
        requests.get = lambda *a, **k: _Resp(200, {"result": "문자열"})
        out["sso_result_not_dict"] = c.post("/api/auth/sso", json={"token": "t"}, headers={"X-Real-IP": GLOBAL_B}).status_code
        db = SessionLocal()
        out["rows_after_outage"] = db.query(models.LoginFailure).filter(
            models.LoginFailure.bucket.like("sso-src:%")).count()
        db.close()
        requests.get = lambda *a, **k: _Resp(200, {"result": {"id": "s0user", "name": "시험", "teamList": []}})
        out["sso_after_outage"] = c.post("/api/auth/sso", json={"token": "ok"}, headers={"X-Real-IP": GLOBAL_A}).status_code
    finally:
        requests.get = real_get
    return out


def mode_cors():
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    return {"ok": preflight(c, "https://ok.metainc.co.kr"), "other": preflight(c, "https://evil.example"),
            "star": preflight(c, "*"), "origins": list(m._cors_origins), "dropped": m._cors_dropped}


def mode_secret():
    """워커 여럿 흉내 — 같은 폴더에서 이 파이썬들이 동시에 app.security 를 불러 같은 값을 쓰는가(해시만)."""
    from app import security
    f = security._fernet
    return {"hash": h(security.JWT_SECRET), "source": security.JWT_SOURCE, "reason": security.JWT_REASON,
            "fernet": h((f._signing_key + f._encryption_key).hex())}


def mode_fernet():
    """암호화 키 첫 생성 — 이미 누가 만든 파일이 있으면 그 키를 쓴다(덮어쓰지 않는다) · 빈 파일이면 채워질 때까지 기다린다."""
    import threading
    import time as _t
    from app import security
    d = os.path.dirname(os.environ["FERNET_KEY_FILE"])
    win = os.path.join(d, "winner.key")
    with open(win, "wb") as fh:
        fh.write(b"WINNERKEY")
    got = security._create_key_once(__import__("pathlib").Path(win))
    with open(win, "rb") as fh:
        after = fh.read()
    late = os.path.join(d, "late.key")
    open(late, "wb").close()                      # 이긴 쪽이 막 만들고 아직 안 쓴 순간
    threading.Timer(0.1, lambda: open(late, "wb").write(b"LATEKEY")).start()
    got2 = security._create_key_once(__import__("pathlib").Path(late))
    fresh = os.path.join(d, "fresh.key")
    got3 = security._create_key_once(__import__("pathlib").Path(fresh))
    mode = __import__("stat").S_IMODE(os.stat(fresh).st_mode)
    return {"kept": got == b"WINNERKEY", "untouched": after == b"WINNERKEY", "waited": got2 == b"LATEKEY",
            "fresh_len": len(got3), "fresh_mode": mode}


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode not in ("secret", "fernet"):
        _hold_collector_lock()
    res = {"boot": mode_boot, "login": mode_login, "cors": mode_cors, "secret": mode_secret,
           "fernet": mode_fernet}[mode]()
    print("@@RESULT@@" + json.dumps(res, ensure_ascii=True))
