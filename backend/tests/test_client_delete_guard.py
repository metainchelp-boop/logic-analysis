"""회귀 — 전산과 연결된 업체는 지우지 못한다 · 삭제는 업체를 고른 뒤에만 (2026-11-28 · 섹션 소식판 ①→② 9/24 요청)

왜 만들었나
  9/10~9/21 사이 전산과 연결된 업체 5곳이 로직분석 화면 삭제로 지워져 보고서가 사라지고 전산 연결이
  끊겼다(신고 #262). 삭제 버튼은 목록 줄에서 자동 분석 멈춤(▶/⏸) 바로 옆에 붙어 있었다.
  대표 결정(11/28 「추천대로」): ①ⓐ 전산 연결 업체는 누구도 못 지움 · ②ⓐ 확인 창에 함께 지워지는 건수 ·
  ③ⓐ 목록 줄에서 빼고 업체를 고른 뒤 머리 오른쪽 「업체 삭제」.

지키는 것
  ① 04:20 담당자 정렬이 받은 전산 연결 목록을 저장한다(미리보기는 저장 안 함 · 빈 목록이 저장된 목록을 지우지 않음).
  ② 삭제 세 경로(화면 · 옛 업체 API · 30일 지난 영업 대상·경쟁사 자동 삭제)가 연결 업체를 막는다 — 함께 지워질 경쟁사가 연결돼 있어도.
  ③ 지우기 직전마다 전산에 새로 묻는다 — 방금 연결된 업체도 막고(교차검증 재현) 방금 끊은 업체는 바로 풀린다.
  ④ 받기 실패 · 온전하지 않은 목록(total ≠ items) · 한꺼번에 20% 넘게 빠진 목록은 저장하지 않고 저장본으로 판단한다.
     자동 삭제는 근거가 전혀 없으면(저장본 없음 + 받기 실패) 그 회차를 건너뛴다.
  ⑤ 삭제 미리보기 = 실제 삭제와 같은 범위(업체 + 붙은 경쟁사)의 건수 · 권한은 삭제와 같다 · 업체 자료는 바꾸지 않는다.
  ⑥ 화면: 목록 줄 ✕ 없음 · 머리 「업체 삭제」 · 미리보기를 묻는 확인 창 · 다시 만든 묶음에도 반영.
네트워크 0 — 전산 조회는 가짜 함수로.
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

TMP = tempfile.mkdtemp(prefix="delete-guard-")
DB = os.path.join(TMP, "t.db")
os.environ["DB_PATH"] = DB
os.environ["REPORTS_DIR"] = os.path.join(TMP, "reports")
os.environ["DEFAULT_ADMIN_PASSWORD"] = "test-only-not-a-secret"
os.environ["ERP_AD_SYNC_API_KEY"] = ""

import erp_link_guard as g   # noqa: E402

passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  ✗", msg)


def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


calls = []


def fake_fetch(ids, fail=False):
    def f():
        calls.append(1)
        if fail:
            raise RuntimeError("전산 조회 실패(가짜)")
        return [{"logic_client_id": i, "manager_login": "m"} for i in ids] + [{"logic_client_id": "x"}]
    return f


def reset_guard():
    c = conn()
    g.ensure_tables(c)
    c.execute("DELETE FROM erp_linked_clients")
    c.execute("DELETE FROM erp_link_sync")
    c.commit()
    c.close()
    calls.clear()


# ① 저장 — 통째로 바꿈 · 빈 목록은 저장된 것을 지우지 않음
reset_guard()
c = conn()
ok(g.ids_from_items([{"logic_client_id": 3}, {"logic_client_id": "4"}, {"logic_client_id": None}, {}]) == {3, 4}, "응답에서 숫자 번호만 고른다")
ok(g.save_linked_set(c, {1, 2, 3}).get("count") == 3, "연결 목록 3곳 저장")
g.save_linked_set(c, {2, 5})
ok({r[0] for r in c.execute("SELECT client_id FROM erp_linked_clients")} == {2, 5}, "새 목록으로 통째로 바꾼다")
r = g.save_linked_set(c, set())
ok(r.get("saved") is False and {r2[0] for r2 in c.execute("SELECT client_id FROM erp_linked_clients")} == {2, 5},
   "새 목록이 비면 저장된 목록을 지우지 않는다(전산 오류로 보호가 한꺼번에 풀리지 않게)")
ok(g.sync_info(c)["count"] == 2, "받은 때와 곳 수를 남긴다")
c.close()

# ③ 지우기 직전마다 새로 묻는다 — 저장본에 없던 새 연결도 막고, 끊은 연결은 풀린다
reset_guard()
c = conn()
g.save_linked_set(c, {10, 11})
ok(g.linked_among(c, [12], fetch=fake_fetch([10, 11, 12])) == {12} and len(calls) == 1,
   "저장본에 없던 새 연결도 지우기 직전에 물어 막는다(교차검증 재현 — 저장본만 보면 지워졌다)")
ok(g.linked_among(c, [10], fetch=fake_fetch([11, 12])) == set() and len(calls) == 2, "전산에서 방금 끊었으면 바로 풀린다")
c.close()

# ④ 받기 실패 · 온전하지 않은 목록 · 한꺼번에 빠진 목록은 저장하지 않고 저장본으로
reset_guard()
c = conn()
g.save_linked_set(c, {20, 21})
ok(g.linked_among(c, [20, 21], fetch=fake_fetch([], fail=True)) == {20, 21}, "받기에 실패하면 저장본으로 판단(연결 업체는 계속 막음)")
_it = lambda n: [{"logic_client_id": i} for i in range(n)]
ok(g.complete(_it(2), 2) and not g.complete(_it(1), 2) and not g.complete(_it(1), None) and not g.complete(_it(1), True), "total = items 개수일 때만 온전한 목록")
big = set(range(1000, 1100))
g.save_linked_set(c, big)
r = g.save_linked_set(c, set(range(1000, 1070)))
ok(r.get("saved") is False and r.get("reason") == "mass-drop" and len(g.stored_linked(c, list(big))) == 100,
   "저장된 100곳 중 30곳이 한꺼번에 빠지면 저장하지 않는다(전산 쪽 오류 대비)")
r = g.save_linked_set(c, set(range(1000, 1090)))
ok(r.get("saved") is True, "10% 정도 빠지는 보통 변화는 저장한다")
# 저장을 거절해도 방금 받은 목록의 연결은 막는다(교차검증 재현 — 대량 누락으로 거절되자 새 연결까지 버렸다)
fresh = set(range(1000, 1060)) | {5000}
st, known = g.link_status(c, [5000, 1085], fetch=fake_fetch(sorted(fresh)))
ok(st == {5000, 1085} and known is True and len(g.stored_linked(c, list(range(1000, 1090)))) == 90,
   "대량 누락이라 저장은 거절해도, 방금 받은 목록의 새 연결(5000)과 저장본의 연결(1085)을 모두 막는다")
# 늦게 도착한 옛 응답은 새 목록을 덮지 않는다
import time as _t   # noqa: E402
t_new = _t.time()
r1 = g.save_linked_set(c, set(range(1000, 1090)) | {6000}, started_at=t_new)
r2 = g.save_linked_set(c, set(range(1000, 1090)), started_at=t_new - 5)
ok(r1.get("saved") and g.stored_linked(c, [6000]) == {6000},
   "먼저 받기 시작한 옛 응답이 나중에 도착해도 더 늦게 본 연결(6000)은 해제하지 못한다")
r3 = g.save_linked_set(c, set(), started_at=t_new - 1)
ok(g.stored_linked(c, [6000]) == {6000} and len(g.stored_linked(c, list(range(1000, 1090)))) == 90,
   "옛 빈 응답도 새 보호를 지우지 못한다")
c.close()

# 두 응답이 엇갈려 도착 — 새 응답(B · 대량 감소라 해제 보류)이 본 새 연결 P 를 옛 응답(A)이 지우지 못한다(교차검증 재현)
reset_guard()
c = conn()
base = set(range(7000, 7025))
g.save_linked_set(c, base, started_at=100.0)
t_b = 200.0
rb = g.save_linked_set(c, set(range(7000, 7010)) | {7999}, started_at=t_b)
ra = g.save_linked_set(c, base, started_at=t_b - 50)
ok(rb.get("held") is True and g.stored_linked(c, [7999]) == {7999} and len(g.stored_linked(c, list(base))) == 25,
   f"대량 감소라 해제는 보류해도 B 가 본 새 연결 7999 는 바로 기록되고, 늦게 온 옛 응답 A 도 지우지 못한다: {rb} {ra}")
c.close()

# 거절한 목록이 20시간 넘게 똑같이 이어지면 진짜 변화로 받아들인다(교차검증 반영 — 거절만 하면 진짜 끊은 연결이 영영 막힘)
reset_guard()
c = conn()
g.save_linked_set(c, set(range(2000, 2030)))
shrunk = set(range(2000, 2010))
ok(g.save_linked_set(c, shrunk).get("reason") == "mass-drop", "대량 누락 첫 번째 = 거절")
ok(g.save_linked_set(c, shrunk).get("reason") == "mass-drop", "20시간 안에 같은 목록이 또 와도 거절")
c.execute("UPDATE erp_link_sync SET pending_since=?", ((datetime.now() - timedelta(hours=21)).isoformat(),))
c.commit()
ok(g.save_linked_set(c, shrunk).get("saved") is True and g.stored_linked(c, [2020]) == set(),
   "같은 목록이 20시간 넘게 이어지면 받아들인다(다음 날 04:20) — 끊은 연결 2020 이 풀린다")
ok(c.execute("SELECT pending_hash FROM erp_link_sync").fetchone()[0] is None, "받아들이면 대기 표시를 지운다")
g.save_linked_set(c, set(range(2000, 2030)))
ok(g.save_linked_set(c, set(range(2000, 2005))).get("saved") is False, "다른 목록이면 대기를 새로 시작")
c.execute("UPDATE erp_link_sync SET pending_since=?", ((datetime.now() - timedelta(hours=21)).isoformat(),))
c.commit()
ok(g.save_linked_set(c, set(range(2000, 2006))).get("saved") is False, "20시간 지났어도 목록이 바뀌었으면 다시 거절")
g.save_linked_set(c, {1})   # 작은 목록으로(빈 목록 규칙 시험용)
c.execute("DELETE FROM erp_linked_clients")
c.execute("INSERT INTO erp_linked_clients VALUES (3000, 'x', 0)")
c.commit()
ok(g.save_linked_set(c, set()).get("reason") == "empty", "빈 목록 첫 번째 = 거절")
c.execute("UPDATE erp_link_sync SET pending_since=?", ((datetime.now() - timedelta(hours=21)).isoformat(),))
c.commit()
ok(g.save_linked_set(c, set()).get("saved") is True and g.stored_linked(c, [3000]) == set(), "빈 목록도 20시간 넘게 이어지면 받아들인다")
c.close()

# 받기 실패 로그에 외부 예외 원문을 남기지 않는다
import logging   # noqa: E402


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


cap = _Cap()
g.logger.addHandler(cap)


def _leaky():
    raise ConnectionError("http://x/?k=SYNTH-SECRET-777")


c = conn()
g.link_status(c, [1], fetch=_leaky)
c.close()
g.logger.removeHandler(cap)
ok(cap.msgs and not any("SYNTH-SECRET-777" in m for m in cap.msgs), f"받기 실패 로그에 외부 예외 원문이 없다: {cap.msgs[-1:]}")
reset_guard()
c = conn()
st, known = g.link_status(c, [30], fetch=fake_fetch([], fail=True))
ok(st == set() and known is False, "지금 전산이 확인해 주지 못하면 known=False(지우지 않는다)")
c.close()

# ① 04:20 담당자 정렬이 목록을 저장한다
import report_owner_sync as ros   # noqa: E402

c = conn()
c.execute("CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY, name TEXT, created_by INTEGER, role TEXT, "
          "competitor_of INTEGER, status TEXT DEFAULT 'active', expires_at TEXT, updated_at TEXT, vertical TEXT, "
          "naver_store_url TEXT, main_keywords TEXT, business_name TEXT, auto_analysis INTEGER DEFAULT 1)")
c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, name TEXT, "
          "role TEXT, is_active INTEGER, created_at TEXT, updated_at TEXT)")
c.commit()
c.close()


class _NoHandover:
    def __init__(self, *a, **k):
        pass

    def initialize(self):
        pass


ros.HandoverTransferService = _NoHandover
reset_guard()
_items78 = [{"logic_client_id": 7, "manager_login": ""}, {"logic_client_id": 8, "manager_login": ""}]
ros.fetch_client_managers_payload = lambda base, key, timeout=15: (_items78, 2)
ros.run_report_owner_sync(db_path=DB, base="http://t", api_key="k", dry_run=True)
c = conn()
ok(c.execute("SELECT COUNT(*) FROM erp_linked_clients").fetchone()[0] == 0, "미리보기(dry_run)는 연결 목록을 저장하지 않는다")
c.close()
ros.run_report_owner_sync(db_path=DB, base="http://t", api_key="k")
c = conn()
ok({r[0] for r in c.execute("SELECT client_id FROM erp_linked_clients")} == {7, 8}, "04:20 담당자 정렬이 받은 연결 목록(담당자 없는 곳 포함)을 저장한다")
c.close()
ros.fetch_client_managers_payload = lambda base, key, timeout=15: ([{"logic_client_id": 7, "manager_login": ""}], 2)
ros.run_report_owner_sync(db_path=DB, base="http://t", api_key="k")
c = conn()
ok({r[0] for r in c.execute("SELECT client_id FROM erp_linked_clients")} == {7, 8},
   "전산이 일부만 준 목록(total 2 · items 1)은 저장하지 않는다 — 8번 보호가 풀리지 않는다(교차검증 재현)")
c.close()
# 지울 때 묻는 기본 받기도 일부만 온 목록은 실패로 본다
ros_payload_partial = lambda base, key, timeout=8: ([{"logic_client_id": 7}], 2)
os.environ["ERP_AD_SYNC_API_KEY"] = "k"
ros.fetch_client_managers_payload = ros_payload_partial
c = conn()
ok(g.linked_among(c, [8]) == {8}, "지울 때 전산이 일부만 주면 실패로 보고 저장본으로 — 8번은 계속 막힌다")
c.close()
ros.fetch_client_managers_payload = lambda base, key, timeout=8: (None, 0)
c = conn()
st, known = g.link_status(c, [8])
ok(known is False and st == {8}, "전산 응답에 목록 칸(items)이 없으면(total 0) 「연결 0곳」이 아니라 확인 못 함(교차검증 재현)")
c.close()
ok(not g.complete(None, 0) and not g.complete([{"logic_client_id": "x"}], 1) and not g.complete([{}], 1) and g.complete([], 0),
   "목록이 아니거나 번호를 못 읽는 줄이 있으면 온전하지 않다")


# 실제 받기 함수 — 전산이 200 {"result":{"total":0}}(items 칸 없음)을 주면 items 를 빈 목록으로 채우지 않는다
class _Resp:
    status_code = 200

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


_real_get = ros.requests.get
_real_payload = getattr(ros, "_orig_payload", None)
import importlib   # noqa: E402
ros_fresh = importlib.reload(ros)   # 위에서 바꿔 끼운 가짜를 걷어 내고 진짜 함수로
ros_fresh.HandoverTransferService = _NoHandover
ros_fresh.requests.get = lambda *a, **k: _Resp({"result": {"total": 0}})
items_x, total_x = ros_fresh.fetch_client_managers_payload("http://t", "k")
ok(items_x is None and total_x == 0 and not g.complete(items_x, total_x),
   f"items 칸이 없으면 None 그대로 — 「연결 0곳」으로 오판하지 않는다: {items_x!r}")
ros_fresh.requests.get = lambda *a, **k: _Resp({"result": {"total": 1, "items": [{"logic_client_id": 9}]}})
ok(ros_fresh.fetch_client_managers_payload("http://t", "k") == ([{"logic_client_id": 9}], 1), "정상 응답은 그대로")
ok(ros_fresh.fetch_client_managers("http://t", "k") == [{"logic_client_id": 9}], "담당자 정렬용 받기는 종전처럼 목록")
ros_fresh.requests.get = lambda *a, **k: _Resp({"result": {"total": 0}})
ok(ros_fresh.fetch_client_managers("http://t", "k") == [], "담당자 정렬용 받기는 items 가 없으면 빈 목록(종전처럼)")
ros_fresh.requests.get = _real_get
os.environ["ERP_AD_SYNC_API_KEY"] = ""

# ②⑤ 삭제 경로 끝까지 — 화면 삭제 · 미리보기 · 옛 업체 API · 자동 삭제
import auth                # noqa: E402
import client_dashboard as cd   # noqa: E402
import clients as clmod    # noqa: E402
import httpx               # noqa: E402
from fastapi import FastAPI   # noqa: E402

cd.DB_PATH = DB
clmod.DB_PATH = DB
cd.init_client_dashboard_db()
c = conn()
from client_purge import CHILD_TABLES   # noqa: E402
for t, col in CHILD_TABLES:
    c.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY, {col} INTEGER)")
c.execute("DELETE FROM clients")
c.executemany("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (?,?,?,?,?)", [
    (101, "연결 업체", 1, "advertiser", None),
    (102, "보통 업체", 1, "advertiser", None),
    (103, "보통 업체의 경쟁사", 1, "competitor", 102),
    (104, "경쟁사가 연결된 업체", 1, "advertiser", None),
    (105, "연결된 경쟁사", 1, "competitor", 104),
    (106, "남의 업체", 2, "advertiser", None),
])
c.executemany("INSERT INTO reports (client_id) VALUES (?)", [(102,), (102,), (102,), (101,), (103,)])
c.executemany("INSERT INTO client_analyses (client_id, keyword) VALUES (?, ?)", [(102, "가"), (102, "나"), (103, "다")])
c.executemany("INSERT INTO client_rank_history (client_id, keyword, checked_at) VALUES (?,?,?)",
              [(102, "가", "2026-11-01 08:00"), (102, "가", "2026-11-01 09:00"), (102, "나", "2026-11-02 08:00"), (103, "다", "2026-11-01 08:00")])
c.execute("INSERT INTO client_rank_history (client_id, keyword, checked_at) VALUES (102, '가', NULL)")   # 날짜 빈 기록은 하루로 세지 않는다
c.commit()
c.close()
reset_guard()
c = conn()
g.save_linked_set(c, {101, 105, 201, 202})
c.close()
g._default_fetch = fake_fetch([101, 105, 201, 202])

USER = {"id": 1, "username": "u1", "role": "manager", "name": "시험"}
ADMIN = {"id": 9, "username": "adm", "role": "superadmin", "name": "관리자"}
who = {"u": USER}
app = FastAPI()
app.include_router(cd.router)
app.include_router(clmod.router)
app.dependency_overrides[auth.get_current_user] = lambda: who["u"]


async def call(method, path):
    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t") as cl:
        return await cl.request(method, path)


def req(method, path):
    return asyncio.run(call(method, path))


def exists(cid):
    c = conn()
    n = c.execute("SELECT COUNT(*) FROM clients WHERE id=?", (cid,)).fetchone()[0]
    c.close()
    return n == 1


r = req("GET", "/api/cd/102/delete-preview")
j = r.json()
ok(r.status_code == 200 and j.get("erp_linked") is False and j.get("reports") == 4 and j.get("analyses") == 3
   and j.get("rank_days") == 3 and j.get("competitors") == 1,
   f"미리보기 건수 = 실제 삭제 범위(업체 + 붙은 경쟁사) — 보고서 4 · 분석 3 · 순위 3일 · 경쟁사 1(교차검증 재현): {j}")
ok(exists(102) and exists(103), "미리보기는 아무것도 지우지 않는다")
r = req("GET", "/api/cd/101/delete-preview")
ok(r.status_code == 200 and r.json().get("erp_linked") is True, "연결 업체 미리보기 = 연결됨")
r = req("GET", "/api/cd/106/delete-preview")
ok(r.status_code == 403, f"남의 업체 미리보기는 삭제와 같이 막힌다: {r.status_code}")

r = req("DELETE", "/api/cd/101")
ok(r.status_code == 409 and "전산" in r.json().get("detail", "") and exists(101), f"연결 업체 화면 삭제 = 409 · 그대로 남음: {r.status_code}")
c = conn()
ok(c.execute("SELECT COUNT(*) FROM reports WHERE client_id=101").fetchone()[0] == 1, "막힌 업체의 보고서도 그대로")
c.close()
who["u"] = ADMIN
r = req("DELETE", "/api/cd/101")
ok(r.status_code == 409 and exists(101), "최고관리자도 연결 업체는 못 지운다(①ⓐ)")
who["u"] = USER
r = req("DELETE", "/api/cd/104")
ok(r.status_code == 409 and exists(104) and exists(105), "함께 지워질 경쟁사가 연결돼 있으면 막는다")
r = req("DELETE", "/api/cd/102")
ok(r.status_code == 200 and not exists(102) and not exists(103), f"연결 안 된 업체는 경쟁사와 함께 지워진다: {r.status_code}")

# ③ 전산에서 끊은 뒤 다시 누르면 바로 지울 수 있다
g._default_fetch = fake_fetch([105, 201, 202])
r = req("DELETE", "/api/cd/101")
ok(r.status_code == 200 and not exists(101), f"전산에서 연결을 끊은 뒤 다시 누르면 바로 지워진다: {r.status_code}")

# 근거 없음 — 저장본이 있어도 지금 전산이 확인 못 해 주면 지우지 않는다(교차검증 재현)
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (120, '확인 못 할 때 보통 업체', 1, 'advertiser')")
c.commit()
c.close()
g._default_fetch = fake_fetch([], fail=True)
r = req("GET", "/api/cd/120/delete-preview")
ok(r.status_code == 200 and r.json().get("erp_known") is False and r.json().get("erp_linked") is False,
   f"전산이 응답 없으면 미리보기 = 확인 못 함: {r.json()}")
r = req("DELETE", "/api/cd/120")
ok(r.status_code == 409 and "확인하지 못해" in r.json().get("detail", "") and exists(120),
   f"전산이 응답 없으면(저장본이 있어도) 연결 안 된 업체도 지우지 않고 「잠시 후 다시」: {r.status_code}")
g._default_fetch = fake_fetch([105, 201, 202])

# 미리보기는 아무것도 쓰지 않는다 — 표가 없으면 만들지도 않는다
c = conn()
c.execute("DROP TABLE erp_linked_clients")
c.execute("DROP TABLE erp_link_sync")
c.commit()
c.close()
r = req("GET", "/api/cd/120/delete-preview")
c = conn()
made = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('erp_linked_clients','erp_link_sync')").fetchone()[0]
c.close()
ok(r.status_code == 200 and made == 0, f"미리보기는 연결 표를 만들거나 저장하지 않는다: 표 {made}개")
# 건수 조회 실패는 0건이 아니라 「확인 못 함」(None)
c = conn()
c.execute("ALTER TABLE reports RENAME TO reports_x")
c.commit()
c.close()
r = req("GET", "/api/cd/120/delete-preview")
c = conn()
c.execute("ALTER TABLE reports_x RENAME TO reports")
c.commit()
c.close()
ok(r.status_code == 200 and r.json().get("reports") is None, f"건수를 못 세면 None(0건과 구분): {r.json().get('reports')!r}")

# 판정과 지우기 사이에 다른 연결이 보호를 기록하면, 쓰기 잠금 안에서 한 번 더 보고 막는다(교차검증 재현)
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (121, '판정 뒤 연결되는 업체', 1, 'advertiser')")
c.commit()
c.close()
_real_ls = g.link_status


def _racy_link_status(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    g.save_linked_set(other, {105, 201, 202, 121})   # 판정 직후 다른 요청이 121 연결을 기록
    other.close()
    return out


g.link_status = _racy_link_status
r = req("DELETE", "/api/cd/121")
g.link_status = _real_ls
ok(r.status_code == 409 and exists(121), f"판정 뒤 기록된 연결도 지우기 직전에 다시 봐서 막는다: {r.status_code}")

# 연결을 정상적으로 끊은 뒤 — 미리보기도 실제 삭제와 같은 답(교차검증 재현: 미리보기만 계속 막혀 삭제로 못 감)
g._default_fetch = fake_fetch([105, 201, 202])
r = req("GET", "/api/cd/121/delete-preview")
ok(r.status_code == 200 and r.json().get("erp_linked") is False and r.json().get("erp_known") is True,
   f"전산에서 끊은 뒤 미리보기 = 연결 아님(실제 삭제와 같은 규칙): {r.json().get('erp_linked')}")
c = conn()
still = g.stored_linked(c, [121])
c.close()
ok(still == {121}, "미리보기는 그래도 저장본을 바꾸지 않는다")
r = req("DELETE", "/api/cd/121")
ok(r.status_code == 200 and not exists(121), f"그리고 실제로 지워진다: {r.status_code}")

# 옛 업체 API 삭제 경로
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (201, '옛 경로 연결 업체', 9, 'advertiser'), (203, '옛 경로 보통 업체', 9, 'advertiser')")
c.commit()
c.close()
who["u"] = ADMIN
r = req("DELETE", "/api/clients/201")
ok(r.status_code == 409 and exists(201), f"옛 업체 API 삭제도 연결 업체를 막는다: {r.status_code}")
r = req("DELETE", "/api/clients/203")
ok(r.status_code == 200 and not exists(203), f"옛 업체 API 로 연결 안 된 업체는 지워진다: {r.status_code}")
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (211, '옛 경로 판정 뒤 연결', 9, 'advertiser')")
c.commit()
c.close()


def _racy211(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    g.save_linked_set(other, {105, 201, 202, 211})
    other.close()
    return out


g.link_status = _racy211
r = req("DELETE", "/api/clients/211")
g.link_status = _real_ls
ok(r.status_code == 409 and exists(211), f"옛 업체 API 도 판정 뒤 기록된 연결을 지우기 직전에 다시 봐서 막는다: {r.status_code}")

# 30일 지난 영업 대상·경쟁사 자동 삭제
past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (202, '기한 지난 연결 영업 대상', 1, 'prospect', ?), (204, '기한 지난 보통 영업 대상', 1, 'prospect', ?)", (past, past))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (205, '연결 영업 대상의 경쟁사', 1, 'competitor', 202)")
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (206, '기한 지난 보통 영업 대상 2', 1, 'prospect', ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (207, '보통 영업 대상에 붙은 연결 경쟁사', 1, 'competitor', 206)")
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (208, '보통 영업 대상에 붙은 보통 경쟁사', 1, 'competitor', 206)")
c.commit()
c.close()
g._default_fetch = fake_fetch([105, 201, 202, 207])
c = conn()
g.save_linked_set(c, {105, 201, 202, 207})
c.close()
n = cd.cleanup_expired_competitors()
ok(exists(202) and exists(205) and not exists(204) and not exists(206) and not exists(208),
   f"자동 삭제는 기한 지난 연결 업체(와 그 경쟁사)를 남기고 보통 업체(와 그 경쟁사)만 지운다: 지운 {n}건")
ok(exists(207) and n == 3, f"연결 안 된 영업 대상을 지울 때 붙어 있던 연결 경쟁사는 남긴다: 지운 {n}건")

# 자동 삭제 — 지금 전산이 확인해 주지 못하면(저장본이 오래됐어도) 그 회차를 건너뛴다(교차검증 재현)
reset_guard()
c = conn()
g.save_linked_set(c, {999})
c.execute("UPDATE erp_link_sync SET synced_at=?", ((datetime.now() - timedelta(days=10)).isoformat(),))
c.commit()
c.close()
g._default_fetch = fake_fetch([], fail=True)
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (209, '근거 없을 때 기한 지난 영업 대상', 1, 'prospect', ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (210, '그 경쟁사', 1, 'competitor', 209)")
c.commit()
c.close()
n = cd.cleanup_expired_competitors()
ok(n == 0 and exists(209) and exists(210), f"오래된 저장본만 있고 지금 못 받으면 자동 삭제는 그 회차를 건너뛴다: 지운 {n}건")

# 자동 삭제 — 연결된 부모에 붙은 경쟁사는 그 경쟁사가 따로 기한이 지나도 남긴다(교차검증 재현)
reset_guard()
g._default_fetch = fake_fetch([300])
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (300, '연결된 광고주', 1, 'advertiser')")
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of, expires_at) VALUES (301, '연결 광고주의 기한 지난 경쟁사', 1, 'competitor', 300, ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (302, '판정 중 기한이 늘어날 영업 대상', 1, 'prospect', ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (303, '그 경쟁사', 1, 'competitor', 302)")
c.commit()
c.close()


def _extend_during(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    other.execute("UPDATE clients SET expires_at=? WHERE id=302", ((datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),))
    other.commit()
    other.close()
    return out


g.link_status = _extend_during
n = cd.cleanup_expired_competitors()
g.link_status = _real_ls
ok(exists(301), "연결된 광고주의 경쟁사는 따로 기한이 지나도 지우지 않는다")
ok(exists(302) and exists(303), f"전산을 기다리는 사이 기한이 늘어난 영업 대상(과 그 경쟁사)은 지우지 않는다(쓰기 안에서 다시 확인 · 앞 시험의 다른 만료분 {n}건은 지움)")

# ⑥ 화면
src = open(os.path.join(HERE, "..", "..", "frontend", "js", "components", "ClientDashboard.jsx"), encoding="utf-8").read()
ok("\\u2715" not in src and "deleteClient(c, e)" not in src, "업체 목록 줄의 ✕ 삭제 버튼이 없다")
ok("openDeleteDialog(selectedClient)" in src and "'업체 삭제'" in src, "업체를 고른 뒤 머리에 「업체 삭제」 버튼")
ok("'/delete-preview'" in src and "window.ClientDeleteDialog" in src and "d.erp_linked" in src, "확인 창이 미리보기를 묻고 연결 업체면 막는다")
ok("'보고서 ' + d.reports + '건과 함께 삭제'" in src, "빨간 버튼 이름에 함께 지워지는 보고서 건수")
ok(src.count("prev.req === req") == 1 and src.count("prev.req === d.req") == 1 and "++delReqRef.current" in src,
   "창마다 번호를 붙여 늦게 온 옛 응답이 다른 업체 창을 덮지 않는다(교차검증 재현)")
ok("d.erp_known === false" in src and "지금은 지울 수 없어요" in src and "!d.data.erp_known" in src,
   "전산 확인을 못 하면 「지금은 지울 수 없어요」 · 삭제 버튼 없음")
ok("'확인 못함'" in src, "건수를 못 세면 「확인 못함」")
import json   # noqa: E402
bj = json.load(open(os.path.join(HERE, "..", "..", "frontend", "dist", "bundle.json"), encoding="utf-8"))
bundle = open(os.path.join(HERE, "..", "..", "frontend", "dist", bj.get("file") or bj.get("bundle") or ""), encoding="utf-8").read() \
    if (bj.get("file") or bj.get("bundle")) else ""
ok(("delete-preview" in bundle and "ClientDeleteDialog" in bundle) or not bundle, "다시 만든 화면 묶음에도 들어 있다")

print(f"client_delete_guard: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
