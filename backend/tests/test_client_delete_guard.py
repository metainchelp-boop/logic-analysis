"""회귀 — 전산과 연결된 업체는 지우지 못한다 · 삭제는 업체를 고른 뒤에만 (2026-11-28 · 섹션 소식판 ①→② 9/24 요청)

왜 만들었나
  9/10~9/21 사이 전산과 연결된 업체 5곳이 로직분석 화면 삭제로 지워져 보고서가 사라지고 전산 연결이
  끊겼다(신고 #262). 삭제 버튼은 목록 줄에서 자동 분석 멈춤(▶/⏸) 바로 옆에 붙어 있었다.
  대표 결정(11/28 「추천대로」): ①ⓐ 전산 연결 업체는 누구도 못 지움 · ②ⓐ 확인 창에 함께 지워지는 건수 ·
  ③ⓐ 목록 줄에서 빼고 업체를 고른 뒤 머리 오른쪽 「업체 삭제」.

지키는 것
  ① 04:20 담당자 정렬이 받은 전산 연결 목록을 저장한다(미리보기는 저장 안 함 · 빈 목록이 저장된 목록을 지우지 않음).
  ② 삭제 세 경로(화면 · 옛 업체 API · 30일 지난 영업 대상·경쟁사 자동 삭제)가 연결 업체를 막는다 — 함께 지워질 경쟁사가 연결돼 있어도.
  ③ 연결됨으로 보이면 전산에 한 번 더 물어 방금 끊은 업체는 바로 지울 수 있다(1분에 한 번까지).
  ④ 목록을 오래 못 받았으면 삭제 때 받아 보고, 못 받으면 저장된 목록으로 판단한다.
  ⑤ 삭제 미리보기 = 함께 지워지는 건수 · 권한은 삭제와 같다 · 아무것도 바꾸지 않는다.
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
    g._last_recheck = 0.0
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

# ③ 연결됨이면 한 번 더 묻는다 · 1분에 한 번까지 · 방금 끊었으면 풀림
reset_guard()
c = conn()
g.save_linked_set(c, {10, 11})
ok(g.linked_among(c, [10, 99], fetch=fake_fetch([10, 11])) == {10} and len(calls) == 1, "연결됨이면 전산에 한 번 더 물어 확인")
ok(g.linked_among(c, [10], fetch=fake_fetch([10, 11])) == {10} and len(calls) == 1, "1분 안에는 다시 묻지 않는다")
g._last_recheck = 0.0
ok(g.linked_among(c, [10], fetch=fake_fetch([11])) == set(), "전산에서 방금 연결을 끊었으면 바로 풀린다")
ok(g.linked_among(c, [99], fetch=fake_fetch([10])) == set() and len(calls) == 2, "연결 안 된 업체는 전산에 묻지 않는다(목록이 최신일 때)")
c.close()

# ④ 오래 못 받았으면 삭제 때 받아 본다 · 실패하면 저장된 목록으로
reset_guard()
c = conn()
g.save_linked_set(c, {20})
c.execute("UPDATE erp_link_sync SET synced_at=?", ((datetime.now() - timedelta(hours=40)).isoformat(),))
c.commit()
g._last_recheck = 1e18   # 다시 묻기는 막아 두고 「오래됨」 받기만 본다
ok(g.linked_among(c, [21], fetch=fake_fetch([20, 21])) == {21} and len(calls) == 1, "36시간 넘게 못 받았으면 받아서 판단(새로 연결된 21)")
c.execute("UPDATE erp_link_sync SET synced_at=?", ((datetime.now() - timedelta(hours=40)).isoformat(),))
c.commit()
ok(g.linked_among(c, [20, 21], fetch=fake_fetch([], fail=True)) == {20, 21}, "받기에 실패하면 저장된 목록으로 판단(삭제가 통째로 막히지 않게 · 연결 업체는 계속 막음)")
c.close()
reset_guard()
c = conn()
ok(g.linked_among(c, [30], fetch=fake_fetch([], fail=True)) == set(), "한 번도 못 받았고 지금도 못 받으면 막을 근거가 없다(종전처럼)")
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
ros.fetch_client_managers = lambda base, key, timeout=15: [{"logic_client_id": 7, "manager_login": ""}, {"logic_client_id": 8, "manager_login": ""}]
ros.run_report_owner_sync(db_path=DB, base="http://t", api_key="k", dry_run=True)
c = conn()
ok(c.execute("SELECT COUNT(*) FROM erp_linked_clients").fetchone()[0] == 0, "미리보기(dry_run)는 연결 목록을 저장하지 않는다")
c.close()
ros.run_report_owner_sync(db_path=DB, base="http://t", api_key="k")
c = conn()
ok({r[0] for r in c.execute("SELECT client_id FROM erp_linked_clients")} == {7, 8}, "04:20 담당자 정렬이 받은 연결 목록(담당자 없는 곳 포함)을 저장한다")
c.close()

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
c.executemany("INSERT INTO reports (client_id) VALUES (?)", [(102,), (102,), (102,), (101,)])
c.executemany("INSERT INTO client_analyses (client_id, keyword) VALUES (?, ?)", [(102, "가"), (102, "나")])
c.executemany("INSERT INTO client_rank_history (client_id, keyword, checked_at) VALUES (?,?,?)",
              [(102, "가", "2026-11-01 08:00"), (102, "가", "2026-11-01 09:00"), (102, "나", "2026-11-02 08:00")])
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
ok(r.status_code == 200 and j.get("erp_linked") is False and j.get("reports") == 3 and j.get("analyses") == 2
   and j.get("rank_days") == 2 and j.get("competitors") == 1, f"미리보기 = 보고서 3 · 분석 2 · 순위 2일 · 경쟁사 1 · 연결 아님: {j}")
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
g._last_recheck = 0.0
r = req("DELETE", "/api/cd/101")
ok(r.status_code == 409 and exists(101), "최고관리자도 연결 업체는 못 지운다(①ⓐ)")
who["u"] = USER
r = req("DELETE", "/api/cd/104")
ok(r.status_code == 409 and exists(104) and exists(105), "함께 지워질 경쟁사가 연결돼 있으면 막는다")
r = req("DELETE", "/api/cd/102")
ok(r.status_code == 200 and not exists(102) and not exists(103), f"연결 안 된 업체는 경쟁사와 함께 지워진다: {r.status_code}")

# ③ 전산에서 끊은 뒤 다시 누르면 바로 지울 수 있다
g._default_fetch = fake_fetch([105, 201, 202])
g._last_recheck = 0.0
r = req("DELETE", "/api/cd/101")
ok(r.status_code == 200 and not exists(101), f"전산에서 연결을 끊은 뒤 다시 누르면 바로 지워진다: {r.status_code}")

# 옛 업체 API 삭제 경로
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (201, '옛 경로 연결 업체', 9, 'advertiser'), (203, '옛 경로 보통 업체', 9, 'advertiser')")
c.commit()
c.close()
who["u"] = ADMIN
g._last_recheck = 0.0
r = req("DELETE", "/api/clients/201")
ok(r.status_code == 409 and exists(201), f"옛 업체 API 삭제도 연결 업체를 막는다: {r.status_code}")
r = req("DELETE", "/api/clients/203")
ok(r.status_code == 200 and not exists(203), f"옛 업체 API 로 연결 안 된 업체는 지워진다: {r.status_code}")

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
g._last_recheck = 0.0
n = cd.cleanup_expired_competitors()
ok(exists(202) and exists(205) and not exists(204) and not exists(206) and not exists(208),
   f"자동 삭제는 기한 지난 연결 업체(와 그 경쟁사)를 남기고 보통 업체(와 그 경쟁사)만 지운다: 지운 {n}건")
ok(exists(207) and n == 3, f"연결 안 된 영업 대상을 지울 때 붙어 있던 연결 경쟁사는 남긴다: 지운 {n}건")

# ⑥ 화면
src = open(os.path.join(HERE, "..", "..", "frontend", "js", "components", "ClientDashboard.jsx"), encoding="utf-8").read()
ok("\\u2715" not in src and "deleteClient(c, e)" not in src, "업체 목록 줄의 ✕ 삭제 버튼이 없다")
ok("openDeleteDialog(selectedClient)" in src and "'업체 삭제'" in src, "업체를 고른 뒤 머리에 「업체 삭제」 버튼")
ok("'/delete-preview'" in src and "window.ClientDeleteDialog" in src and "d.erp_linked" in src, "확인 창이 미리보기를 묻고 연결 업체면 막는다")
ok("'보고서 ' + d.reports + '건과 함께 삭제'" in src, "빨간 버튼 이름에 함께 지워지는 보고서 건수")
import json   # noqa: E402
bj = json.load(open(os.path.join(HERE, "..", "..", "frontend", "dist", "bundle.json"), encoding="utf-8"))
bundle = open(os.path.join(HERE, "..", "..", "frontend", "dist", bj.get("file") or bj.get("bundle") or ""), encoding="utf-8").read() \
    if (bj.get("file") or bj.get("bundle")) else ""
ok(("delete-preview" in bundle and "ClientDeleteDialog" in bundle) or not bundle, "다시 만든 화면 묶음에도 들어 있다")

print(f"client_delete_guard: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
