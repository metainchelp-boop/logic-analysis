"""회귀 — 로그인 기록·공개 열람 제한이 실제 접속 주소를 쓴다 (2026-11-28 · 섹션 소식판 ①→② 9/24 요청)

왜 만들었나
  nginx 뒤 도커라 앱이 보는 상대 주소는 늘 게이트웨이 하나였다 — 로그인 기록 10/1 이후 4,550건이 전부 같은 사설 주소.
  공개 보고서 열람의 분당 제한도 열람자 전체가 한 주소로 묶였다.

지키는 것
  ① 상대가 사설·루프백(같은 서버 nginx)이면 nginx 가 덮어쓴 X-Real-IP → 없으면 X-Forwarded-For 맨 뒤 하나.
  ② 상대가 바깥 주소면 헤더를 믿지 않는다(지어낸 헤더로 주소를 속이지 못함).
  ③ 헤더 값이 주소 모양이 아니면 버리고 상대 주소로.
  ④ 로그인(성공 기록 · 시도 제한 · 전산 SSO)과 공개 열람 제한 두 곳이 모두 이 함수를 쓴다(옛 `client.host` 직접 읽기 0).
네트워크 0.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

from starlette.datastructures import Headers   # noqa: E402

from client_ip import client_ip   # noqa: E402

passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  ✗", msg)


class _Client:
    def __init__(self, host):
        self.host = host


class _Req:
    def __init__(self, peer, headers=None):
        self.client = _Client(peer) if peer is not None else None
        self.headers = Headers(headers or {})


GW = "172.18.0.1"
ok(client_ip(_Req(GW, {"X-Real-IP": "203.0.113.7"})) == "203.0.113.7", "nginx 뒤(사설 상대) → X-Real-IP")
ok(client_ip(_Req("127.0.0.1", {"X-Real-IP": "203.0.113.8"})) == "203.0.113.8", "루프백 상대도 nginx 로 본다")
ok(client_ip(_Req(GW, {"X-Forwarded-For": "1.2.3.4, 198.51.100.9"})) == "198.51.100.9",
   "X-Real-IP 가 없으면 X-Forwarded-For 맨 뒤(nginx 가 덧붙인 것)")
ok(client_ip(_Req(GW, {"X-Real-IP": "not-an-ip", "X-Forwarded-For": "198.51.100.10"})) == "198.51.100.10",
   "X-Real-IP 가 주소 모양이 아니면 X-Forwarded-For 로")
ok(client_ip(_Req(GW, {"X-Real-IP": "x", "X-Forwarded-For": "y"})) == GW, "둘 다 주소가 아니면 상대 주소 그대로")
ok(client_ip(_Req(GW)) == GW, "헤더가 없으면 상대 주소 그대로")
ok(client_ip(_Req("203.0.113.50", {"X-Real-IP": "8.8.8.8", "X-Forwarded-For": "8.8.4.4"})) == "203.0.113.50",
   "바깥 주소에서 곧장 온 요청의 헤더는 믿지 않는다(주소 속이기 막기)")
ok(client_ip(_Req(GW, {"X-Real-IP": "2001:db8::1"})) == "2001:db8::1", "IPv6 주소도 받는다")
ok(client_ip(_Req("1.1.1.1", {"X-Real-IP": "8.8.8.8"})) == "1.1.1.1", "공인 주소 상대의 헤더도 믿지 않는다")
ok(client_ip(_Req("100.64.0.1", {"X-Real-IP": "8.8.8.8"})) == "100.64.0.1", "통신사 공유 대역(100.64/10)은 nginx 로 보지 않는다")
ok(client_ip(_Req("10.1.2.3", {"X-Real-IP": "8.8.8.8"})) == "8.8.8.8" and client_ip(_Req("192.168.0.9", {"X-Real-IP": "8.8.8.8"})) == "8.8.8.8",
   "다른 내부망 대역(10/8 · 192.168/16)도 nginx 로 본다")
ok(client_ip(_Req("::1", {"X-Real-IP": "8.8.8.8"})) == "8.8.8.8", "IPv6 루프백도 nginx 로 본다")
ok(client_ip(_Req(None)) == "" and client_ip(_Req(None), "unknown") == "unknown", "상대 주소가 없으면 기본값")
ok(client_ip(None, "unknown") == "unknown", "요청이 없어도 터지지 않는다")
ok(client_ip(_Req("testclient", {"X-Real-IP": "9.9.9.9"})) == "testclient", "상대가 주소 모양이 아니면 헤더를 믿지 않는다")

# ④ 쓰는 곳 — 옛 직접 읽기가 남지 않았다
auth = open(os.path.join(HERE, "..", "auth.py"), encoding="utf-8").read()
reports = open(os.path.join(HERE, "..", "reports.py"), encoding="utf-8").read()
ok("client.host" not in auth, "auth.py 에 상대 주소 직접 읽기가 남지 않았다")
ok(len(re.findall(r"client_ip\(request_obj\)", auth)) == 3, "로그인 시도 제한 · 로그인 기록 · 전산 SSO 기록 세 곳이 실제 주소를 쓴다")
ok("client.host" not in reports, "reports.py 에 상대 주소 직접 읽기가 남지 않았다")
ok(len(re.findall(r"viewer_ip = client_ip\(request, \"unknown\"\)", reports)) == 2
   and len(re.findall(r"_check_view_rate\(viewer_ip\)", reports)) == 2,
   "공개 보고서 열람 두 경로의 분당 제한이 실제 주소로 센다")

# ⑤ 실제 로그인 경로 끝까지 — nginx 뒤(게이트웨이 상대 + X-Real-IP)로 로그인하면 기록에 실제 주소가 남는다
import asyncio      # noqa: E402
import sqlite3      # noqa: E402
import tempfile     # noqa: E402

TMP = tempfile.mkdtemp(prefix="client-ip-")
os.environ["DB_PATH"] = os.path.join(TMP, "t.db")
os.environ["DEFAULT_ADMIN_PASSWORD"] = "test-only-not-a-secret"   # 합성값 고정 — 실제 환경값을 쓰지 않고 임시 관리자 비밀번호도 로그에 안 찍힘
import auth          # noqa: E402
auth.DB_PATH = os.environ["DB_PATH"]
try:
    import httpx                     # noqa: E402
    from fastapi import FastAPI      # noqa: E402
    auth.init_auth_db()
    auth.create_user("ipcheck", "pw-123456!", name="시험", role="viewer")
    app = FastAPI()
    app.include_router(auth.router)

    async def _login(peer, headers):
        tr = httpx.ASGITransport(app=app, client=(peer, 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://t") as c:
            return await c.post("/api/auth/login", json={"username": "ipcheck", "password": "pw-123456!"}, headers=headers)

    r1 = asyncio.run(_login(GW, {"X-Real-IP": "198.51.100.77"}))
    r2 = asyncio.run(_login("1.1.1.1", {"X-Real-IP": "8.8.8.8"}))
    con = sqlite3.connect(os.environ["DB_PATH"])
    ips = [row[0] for row in con.execute("SELECT ip_address FROM login_logs WHERE username='ipcheck' ORDER BY id")]
    con.close()
    ok(r1.status_code == 200 and r2.status_code == 200, f"시험 로그인 성공: {r1.status_code} {r2.status_code}")
    ok(ips == ["198.51.100.77", "1.1.1.1"], f"로그인 기록 = nginx 뒤면 실제 주소 · 바깥 상대면 상대 주소: {ips}")
except Exception as e:
    ok(False, f"실제 로그인 경로 시험 실행 실패: {type(e).__name__}: {e}")

# ⑥ 공개 열람 분당 제한 — 겹친 요청에도 500 이 없고 한도가 정확하다(2026-11-28 교차검증 재현)
#    실제 주소로 세면 키가 1,000개를 넘기 쉬워 정리 분기에 들어간다 — 옛 코드는 두 요청이 같은 만료 키를 함께 지워 KeyError.
import threading     # noqa: E402
import time          # noqa: E402
from collections import defaultdict     # noqa: E402
from datetime import datetime, timedelta   # noqa: E402

os.environ["REPORTS_DIR"] = os.path.join(TMP, "reports")
try:
    import reports   # noqa: E402

    class _SlowTracker(defaultdict):
        """경합 창을 넓힌 집계표 — 읽기마다 잠깐 쉰다(잠금이 없으면 겹친 요청이 서로 끼어든다)."""
        def items(self):
            out = list(super().items())
            time.sleep(0.05)
            return out

        def get(self, k, d=None):
            v = super().get(k, d)
            time.sleep(0.002)
            return v

        def __getitem__(self, k):
            v = super().__getitem__(k)
            time.sleep(0.002)
            return v

    old_ts = datetime.now() - timedelta(minutes=10)
    reports._view_tracker = _SlowTracker(list, {f"10.9.{i // 250}.{i % 250}": [old_ts] for i in range(1001)})
    errors, results = [], []
    gate = threading.Barrier(2)

    def _view(ip):
        try:
            gate.wait(5)
            results.append(reports._check_view_rate(ip))
        except Exception as e:
            errors.append(type(e).__name__)

    ts = [threading.Thread(target=_view, args=(ip,)) for ip in ("198.51.100.1", "198.51.100.2")]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    ok(not errors and results == [True, True], f"만료 키 정리가 겹쳐도 예외 없이 둘 다 열람: 예외 {errors} · 결과 {results}")
    ok(len(reports._view_tracker) == 2, f"만료된 1,001개는 정리되고 지금 두 주소만 남는다: {len(reports._view_tracker)}")

    reports._view_tracker = _SlowTracker(list)
    oks = []
    lock = threading.Lock()
    gate2 = threading.Barrier(40)

    def _same(ip):
        gate2.wait(5)
        r = reports._check_view_rate(ip, limit=30)
        with lock:
            oks.append(r)

    ts = [threading.Thread(target=_same, args=("198.51.100.9",)) for _ in range(40)]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    ok(oks.count(True) == 30 and oks.count(False) == 10, f"같은 주소 40번이 겹쳐도 분당 30번만 통과: 통과 {oks.count(True)} · 막힘 {oks.count(False)}")
except Exception as e:
    ok(False, f"공개 열람 제한 경합 시험 실행 실패: {type(e).__name__}: {e}")
ok(client_ip(_Req("::ffff:172.18.0.1", {"X-Real-IP": "198.51.100.33"})) == "198.51.100.33", "IPv6 로 감싼 내부 주소 상대도 nginx 로 본다")
ok(client_ip(_Req("::ffff:1.1.1.1", {"X-Real-IP": "8.8.8.8"})) == "::ffff:1.1.1.1", "IPv6 로 감싼 공인 주소 상대의 헤더는 믿지 않는다")

print(f"client_ip: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
