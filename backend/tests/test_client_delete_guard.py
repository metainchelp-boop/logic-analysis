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


import time as _t   # noqa: E402


def tick():
    """시계를 조금 넘긴다 — 「기록한 뒤에 시작한 응답」 순서를 시험에서 확실히 만들려고."""
    _t.sleep(0.005)
    return _t.time()


def age_pending(c, hours=21):
    """보류 시계(번호마다)를 hours 만큼 과거로 — 20시간 확인을 시험에서 흉내 낸다."""
    import json as _json
    row = c.execute("SELECT pending_remove FROM erp_link_sync WHERE id = 1").fetchone()
    if row and row[0]:
        d = {k: v - hours * 3600 for k, v in _json.loads(row[0]).items()}
        c.execute("UPDATE erp_link_sync SET pending_remove=? WHERE id = 1", (_json.dumps(d),))
    c.commit()


def pending_ids(c):
    import json as _json
    row = c.execute("SELECT pending_remove FROM erp_link_sync WHERE id = 1").fetchone()
    return {int(k) for k in _json.loads(row[0])} if row and row[0] else set()


# ① 저장 — 응답에 보인 연결은 더하고, 기록한 뒤에 시작한 응답이 빠뜨린 연결은 해제
reset_guard()
c = conn()
ok(g.ids_from_items([{"logic_client_id": 3}, {"logic_client_id": "4"}, {"logic_client_id": None}, {}]) == {3, 4}, "응답에서 숫자 번호만 고른다")
ok(g.ids_from_items([{"logic_client_id": 3.5}, {"logic_client_id": " 6"}, {"logic_client_id": "\uff17"}, {"logic_client_id": True},
                     {"logic_client_id": -1}, {"logic_client_id": "8.0"}]) == set(),
   "소수(3.5)·공백·전각 숫자·참거짓·음수·「8.0」 은 번호로 받지 않는다(교차검증 반영 — 3.5 가 3 으로 잘렸다)")
ok(g.complete([{"logic_client_id": 3.5}], 1) is False and g.complete([{"logic_client_id": "3"}, {"logic_client_id": 4}], 2) is True,
   "소수 번호가 하나라도 있으면 온전하지 않다 · 숫자 글자·정수는 온전")
g.save_linked_set(c, {1, 2, 3})
tick()
g.save_linked_set(c, {2, 5})
ok(g.stored_linked(c, [1, 2, 3, 5]) == {2, 5}, "기록한 뒤에 시작한 응답이 빠뜨린 연결(1·3)은 해제하고 새 연결(5)은 더한다")
tick()
r = g.save_linked_set(c, set())
ok(r.get("held") is True and g.stored_linked(c, [2, 5]) == {2, 5}, "빈 목록은 해제를 보류한다(전산 오류로 보호가 한꺼번에 풀리지 않게)")
ok(g.sync_info(c)["count"] == 2, "반영한 때와 곳 수를 남긴다")
age_pending(c)
tick()
ok(g.save_linked_set(c, set()).get("saved") is True and g.stored_linked(c, [2, 5]) == set(), "빈 목록도 그 번호들이 20시간 넘게 계속 빠져 있으면 해제")
c.close()

# ③ 지우기 직전마다 새로 묻는다 — 저장본에 없던 새 연결도 막고, 끊은 연결은 풀린다
reset_guard()
c = conn()
g.save_linked_set(c, {10, 11})
tick()
ok(g.linked_among(c, [12], fetch=fake_fetch([10, 11, 12])) == {12} and len(calls) == 1,
   "저장본에 없던 새 연결도 지우기 직전에 물어 막는다(교차검증 재현 — 저장본만 보면 지워졌다)")
tick()
ok(g.linked_among(c, [10], fetch=fake_fetch([11, 12])) == set() and len(calls) == 2, "전산에서 방금 끊었으면 바로 풀린다")
c.close()

# ④ 받기 실패 · 불완전 목록
reset_guard()
c = conn()
g.save_linked_set(c, {20, 21})
st, known = g.link_status(c, [20, 21], fetch=fake_fetch([], fail=True))
ok(st == {20, 21} and known is False, "받기에 실패하면 저장본으로 막되 확인 못 함(known=False — 지우지 않는다)")
_it = lambda n: [{"logic_client_id": i} for i in range(n)]
ok(g.complete(_it(2), 2) and not g.complete(_it(1), 2) and not g.complete(_it(1), None) and not g.complete(_it(1), True), "total = items 개수일 때만 온전한 목록")
c.close()
reset_guard()
c = conn()
st, known = g.link_status(c, [30], fetch=fake_fetch([], fail=True))
ok(st == set() and known is False, "지금 전산이 확인해 주지 못하면 known=False(지우지 않는다)")
c.close()

# 대량 해제 — 보통 변화(10%)는 반영, 20% 넘으면 보류하되 방금 받은 새 연결은 더한다
reset_guard()
c = conn()
big = set(range(1000, 1100))
g.save_linked_set(c, big)
tick()
ok(g.save_linked_set(c, set(range(1000, 1090))).get("saved") is True and len(g.stored_linked(c, list(big))) == 90, "10% 정도 빠지는 보통 변화는 반영")
reset_guard()
c.close()
c = conn()
g.save_linked_set(c, big)
tick()
r = g.save_linked_set(c, set(range(1000, 1070)))
ok(r.get("held") is True and len(g.stored_linked(c, list(big))) == 100, "저장된 100곳 중 30곳이 한꺼번에 빠지면 해제를 보류(전산 쪽 오류 대비)")
tick()
st, known = g.link_status(c, [5000, 1085], fetch=fake_fetch(sorted(set(range(1000, 1060)) | {5000})))
ok(st == {5000, 1085} and known is True, "대량 해제라 보류해도 방금 받은 새 연결(5000)은 더하고 저장본의 연결(1085)도 막는다(교차검증 재현)")
c.close()

# 순서 — 기록한 뒤에 시작한 응답만 해제할 수 있다
reset_guard()
c = conn()
t_old = _t.time()            # A: 먼저 시작한 요청(나중에 「연결 없음」으로 늦게 도착)
tick()
g.save_linked_set(c, {6000, 6001})   # 그 사이 다른 요청이 6000 연결을 기록
r = g.save_linked_set(c, {6001}, started_at=t_old)
ok(g.stored_linked(c, [6000]) == {6000}, "기록 전에 시작한 옛 응답은 그 연결을 해제하지 못한다")
r = g.save_linked_set(c, set(), started_at=t_old)
ok(g.stored_linked(c, [6000, 6001]) == {6000, 6001}, "기록 전에 시작한 옛 빈 응답도 보호를 지우지 못한다")
c.close()

# 순서 반례(교차검증 재현) — A 먼저 시작 → B 나중 시작했지만 「연결 없음」을 먼저 읽음 → A 가 「연결 있음」을 기록 → B 도착.
# 받기 시작 시각만 비교하면 B(나중 시작)가 보호를 풀었다. 기록한 시각으로 비교하면 B 는 기록 전에 시작했으니 못 푼다.
reset_guard()
c = conn()
g.save_linked_set(c, {7100})
t_a = tick()                 # A 시작
t_b = tick()                 # B 시작(A 보다 나중) — B 는 이때 전산에서 7200 없음을 읽었다고 하자
tick()
g.save_linked_set(c, {7100, 7200}, started_at=t_a)   # A 가 늦게 읽은 「7200 연결」을 기록(기록 시각 > t_b)
g.save_linked_set(c, {7100}, started_at=t_b)          # B 의 지연된 「7200 없음」 도착
ok(g.stored_linked(c, [7200]) == {7200}, "나중에 시작했어도 우리가 기록하기 전에 시작한 응답(B)은 그 연결을 해제하지 못한다")
tick()
g.save_linked_set(c, {7100})                           # 기록 뒤에 시작한 응답의 「7200 없음」 → 진짜 해제
ok(g.stored_linked(c, [7200]) == set(), "기록한 뒤에 시작한 응답의 해제는 반영")
c.close()

# 두 응답이 엇갈려 도착 — B(대량 감소라 보류)가 본 새 연결 P 를 옛 응답 A 가 지우지 못한다(교차검증 재현)
reset_guard()
c = conn()
base = set(range(7000, 7025))
g.save_linked_set(c, base)
t_a = tick()
tick()
rb = g.save_linked_set(c, set(range(7000, 7010)) | {7999})
ra = g.save_linked_set(c, base, started_at=t_a)
ok(rb.get("held") is True and g.stored_linked(c, [7999]) == {7999} and len(g.stored_linked(c, list(base))) == 25,
   f"대량 감소라 해제는 보류해도 B 가 본 새 연결 7999 는 기록되고, 옛 응답 A 도 지우지 못한다: {rb} {ra}")
c.close()

# 보류는 「보류된 번호들」에 건다 — 다시 나타난 번호는 빠지고, 나머지는 20시간 넘게 계속 빠져 있어야 해제
reset_guard()
c = conn()
g.save_linked_set(c, set(range(2000, 2030)))
tick()
shrunk = set(range(2000, 2010))
ok(g.save_linked_set(c, shrunk).get("held") is True, "대량 해제 첫 번째 = 보류")
tick()
ok(g.save_linked_set(c, shrunk).get("held") is True, "20시간 안에 같은 응답이 또 와도 보류")
tick()
r = g.save_linked_set(c, shrunk | {2029})
ok(r.get("held") is True and g.stored_linked(c, [2029, 2010]) == {2029, 2010}, "다시 나타난 번호(2029)는 남고 나머지 보류는 그대로")
age_pending(c)
tick()
ok(g.save_linked_set(c, shrunk | {2029}).get("saved") is True and g.stored_linked(c, [2010]) == set() and g.stored_linked(c, [2029]) == {2029},
   "보류된 번호들이 20시간 넘게 계속 빠져 있으면 해제(다시 나타난 2029 는 남음)")
ok(pending_ids(c) == {2029}, "해제한 번호는 보류에서 빠지고, 다시 보인 2029 만 보류(시계 새로)로 남는다")
c.close()

# 같은 대량 해제 응답이 곧바로 한 번 더 와도 보류가 풀리지 않는다(교차검증 재현 — 새 연결이 더해져 비율이 낮아지며 풀렸다)
reset_guard()
c2 = conn()
g.save_linked_set(c2, set(range(4000, 4020)))
tick()
resp = (set(range(4000, 4020)) - set(range(4000, 4005))) | set(range(4100, 4105))
r1 = g.save_linked_set(c2, resp)
tick()
r2 = g.save_linked_set(c2, resp)
ok(r1.get("held") is True and r2.get("held") is True and g.stored_linked(c2, list(range(4000, 4005))) == set(range(4000, 4005)),
   f"보류된 해제는 같은 응답이 다시 와도 20시간 전엔 풀리지 않는다: {r1} {r2}")
c2.close()

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
for _big in ("9223372036854775808", 2 ** 63, "1" * 5000):
    ros.fetch_client_managers_payload = lambda base, key, timeout=8, _b=_big: ([{"logic_client_id": _b}], 1)
    c = conn()
    try:
        st, known = g.link_status(c, [8])
    except Exception as _e:          # 예외 = 운영에서는 500
        st, known = type(_e).__name__, "예외"
    ok(known is False and st == {8}, f"DB 에 못 담는 번호({str(_big)[:12]}…)가 오면 확인 못 함 — 삭제 500 이 아니라 409(교차검증 재현): {known}")
    c.close()
ok(g.complete([{"logic_client_id": "9223372036854775807"}], 1) and g._parse_id(2 ** 63 - 1) == 2 ** 63 - 1,
   "DB 에 담기는 가장 큰 번호까지는 받는다")
try:
    _r_long = g.complete([{"logic_client_id": "1" * 5000}], 1)
except Exception:
    _r_long = "예외"
ok(_r_long is False, f"아주 긴 숫자 글자는 예외 없이 온전하지 않음으로 본다(정기 정렬이 멈추지 않게): {_r_long}")
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
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (212, '옛 경로 판정 중 주인 바뀜', 1, 'advertiser')")
c.commit()
c.close()


def _owner_change(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    other.execute("UPDATE clients SET created_by=2 WHERE id=212")
    other.commit()
    other.close()
    return out


who["u"] = USER
g.link_status = _owner_change
r = req("DELETE", "/api/clients/212")
g.link_status = _real_ls
who["u"] = ADMIN
ok(r.status_code == 403 and exists(212), f"옛 업체 API — 판정 중 주인이 바뀌면 지우기 직전에 다시 봐서 막는다(교차검증 재현): {r.status_code}")

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
ok(exists(202) and exists(205) and not exists(204),
   f"자동 삭제는 기한 지난 연결 업체(와 그 경쟁사)를 남기고 보통 업체만 지운다: 지운 {n}건")
ok(exists(206) and exists(207) and exists(208) and n == 1,
   f"연결된 경쟁사가 붙은 영업 대상은 묶음 전체를 남긴다 — 부모만 지워 비교가 끊기지 않게(사람이 지울 때 409 와 같은 규칙 · 교차검증 반영): 지운 {n}건")

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

# 전산을 기다리는 사이 기한 지난 경쟁사가 다른 「연결된」 부모로 옮겨지면 남긴다(교차검증 재현)
reset_guard()
g._default_fetch = fake_fetch([300, 310])
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role) VALUES (310, '새로 연결된 광고주', 1, 'advertiser')")
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (311, '보통 영업 대상', 1, 'prospect', NULL)")
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of, expires_at) VALUES (312, '옮겨질 기한 지난 경쟁사', 1, 'competitor', 311, ?)", (past,))
c.commit()
c.close()


def _move_during(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    other.execute("UPDATE clients SET competitor_of=310 WHERE id=312")
    other.commit()
    other.close()
    return out


g.link_status = _move_during
cd.cleanup_expired_competitors()
g.link_status = _real_ls
ok(exists(312), "판정 중 연결된 부모(310)로 옮겨진 기한 지난 경쟁사는 지우지 않는다")

# 전산을 기다리는 사이 기한 지난 영업 대상에 경쟁사가 새로 붙으면 부모를 남긴다 — 고아 방지(교차검증 7차 재현)
reset_guard()
g._default_fetch = fake_fetch([999])
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (320, '기한 지난 영업 대상', 1, 'prospect', ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (321, '먼저 붙어 있던 경쟁사', 1, 'competitor', 320)")
c.commit()
c.close()


def _register_during(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    other.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (322, '기다리는 사이 새로 붙은 경쟁사', 2, 'competitor', 320)")
    other.commit()
    other.close()
    return out


g.link_status = _register_during
n = cd.cleanup_expired_competitors()
g.link_status = _real_ls
c = conn()
_par = c.execute("SELECT competitor_of FROM clients WHERE id = 322").fetchone()
c.close()
ok(exists(320) and exists(321) and exists(322) and _par and _par[0] == 320,
   f"판정 중 경쟁사가 새로 붙은 영업 대상은 이번 회차에 남긴다 — 새 경쟁사가 없는 부모를 가리키지 않는다: 지운 {n}건")
n = cd.cleanup_expired_competitors()
ok(not exists(320) and not exists(321) and not exists(322) and n == 3,
   f"다음 회차에는 새 경쟁사까지 함께 전산에 묻고 정리한다: 지운 {n}건")

# 판정 중 새로 붙은 경쟁사가 다음 회차에 전산 연결로 확인되면 부모를 남긴다(교차검증 8차 재현)
reset_guard()
g._default_fetch = fake_fetch([999])
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (330, '기한 지난 영업 대상', 1, 'prospect', ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (331, '먼저 붙어 있던 경쟁사', 1, 'competitor', 330)")
c.commit()
c.close()


def _register_during2(cn, ids, fetch=None, save=True):
    out = _real_ls(cn, ids, fetch, save)
    other = conn()
    other.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (332, '기다리는 사이 새로 붙은 경쟁사', 2, 'competitor', 330)")
    other.commit()
    other.close()
    return out


g.link_status = _register_during2
cd.cleanup_expired_competitors()
g.link_status = _real_ls
g._default_fetch = fake_fetch([999, 332])
n = cd.cleanup_expired_competitors()
ok(exists(330) and exists(331) and exists(332) and n == 0,
   f"다음 회차에 새 경쟁사가 전산 연결로 확인되면 부모·다른 경쟁사도 남긴다 — 연결 경쟁사의 비교가 끊기지 않게: 지운 {n}건")
r = req("GET", "/api/cd/330/competitors")
ok(r.status_code == 200, f"그 영업 대상의 경쟁사 목록이 계속 열린다: {r.status_code}")

# 범위 확인 — 같은 부모의 다른 경쟁사(형제)가 연결이어도, 연결 안 된 경쟁사가 스스로 기한이 지나면 지운다(의도한 범위)
reset_guard()
g._default_fetch = fake_fetch([999, 341])
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role, expires_at) VALUES (340, '기한 지난 영업 대상', 1, 'prospect', ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (341, '연결된 경쟁사', 1, 'competitor', 340)")
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of, expires_at) VALUES (342, '스스로 기한 지난 연결 안 된 경쟁사', 1, 'competitor', 340, ?)", (past,))
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (343, '기한 전 연결 안 된 경쟁사', 1, 'competitor', 340)")
c.commit()
c.close()
n = cd.cleanup_expired_competitors()
ok(exists(340) and exists(341) and exists(343) and not exists(342),
   f"연결 경쟁사가 붙은 부모·연결 경쟁사·기한 전 경쟁사는 남고, 스스로 기한 지난 연결 안 된 형제만 지운다: "
   f"{[i for i in (340, 341, 342, 343) if exists(i)]}")
r = req("GET", "/api/cd/340/competitors")
ok(r.status_code == 200, f"부모의 경쟁사 목록은 계속 열린다(연결 경쟁사 비교 유지): {r.status_code}")
who["u"] = ADMIN
c = conn()
c.execute("INSERT INTO clients (id, name, created_by, role, competitor_of) VALUES (344, '사람이 지울 연결 안 된 형제', 1, 'competitor', 340)")
c.execute("INSERT INTO reports (client_id) VALUES (344)")
c.commit()
c.close()
r344 = req("DELETE", "/api/cd/344")
c = conn()
_rep344 = c.execute("SELECT COUNT(*) FROM reports WHERE client_id = 344").fetchone()[0]
c.close()
ok(r344.status_code == 200 and not exists(344) and _rep344 == 0,
   f"사람이 연결 안 된 형제 하나를 지우면 막지 않는다(행·보고서 정리 · 연결 형제가 있어도): {r344.status_code}")
ok(req("DELETE", "/api/cd/340").status_code == 409 and req("DELETE", "/api/cd/341").status_code == 409 and exists(340) and exists(341),
   "사람이 지울 때도 같은 범위 — 부모(붙은 연결 경쟁사)와 연결 경쟁사는 409")

# ⑥ 화면

# 교차검증 5차 반례 — 보류를 바꿀 자격이 없는 늦은 응답이 보류를 비우지 못한다
reset_guard()
c = conn()
t_a = tick()                                   # A 는 보호 20곳 기록 전에 시작(오래 걸림)
tick()
base = set(range(7300, 7320))
g.save_linked_set(c, base)
tick()
b_list = set(range(7305, 7320)) | set(range(7400, 7405))      # 기존 5개 빠짐 + 새 5개
rb = g.save_linked_set(c, b_list)
ok(rb.get("held") is True and pending_ids(c) == set(range(7300, 7305)), f"B: 5/20 = 25% 라 보류: {rb}")
ra = g.save_linked_set(c, b_list, started_at=t_a)
ok(pending_ids(c) == set(range(7300, 7305)), f"늦게 온 A(같은 목록 · 해제 자격 없음)가 보류를 비우지 못한다: {ra}")
tick()
rc = g.save_linked_set(c, b_list)
ok(rc.get("held") is True and g.stored_linked(c, range(7300, 7305)) == set(range(7300, 7305)),
   f"그 뒤 같은 목록(5/25 = 20%)이 와도 20시간 전에는 해제하지 않는다: {rc}")
ok(g.link_status(c, [7300], fetch=fake_fetch(sorted(b_list)))[0] == {7300}, "그동안 지우려 해도 연결로 막힌다")
c.close()

# 보류 중 늦게 온 「보임」 응답 — 보류는 그대로, 그 번호의 시계만 새로(그 뒤로 다시 20시간)
reset_guard()
c = conn()
g.save_linked_set(c, set(range(7500, 7520)))
t_old = tick()
tick()
g.save_linked_set(c, set(range(7505, 7520)))   # 5개 보류
age_pending(c)                                  # 21시간 지난 셈
g.save_linked_set(c, set(range(7500, 7520)), started_at=t_old)   # 보류 전에 시작한 응답이 5개를 「보임」으로
ok(pending_ids(c) == set(range(7500, 7505)), "늦게 온 「보임」 응답은 보류를 풀지 않는다")
tick()
g.save_linked_set(c, set(range(7505, 7520)))
ok(g.stored_linked(c, range(7500, 7505)) == set(range(7500, 7505)), "보인 뒤로 20시간이 지나지 않았으니 다시 빠져도 해제하지 않는다")
age_pending(c)
tick()
g.save_linked_set(c, set(range(7505, 7520)))
ok(g.stored_linked(c, range(7500, 7505)) == set() and pending_ids(c) == set(), "보인 뒤로 20시간 넘게 계속 빠지면 해제")
c.close()


# 20시간 경계 — 경계 직전에 시작해 경계 뒤에 도착한 응답은 해제하지 못한다(교차검증 6차 재현)
import types as _types0  # noqa: E402
_rt0 = g.time
_clk = [3_000_000.0]
g.time = _types0.SimpleNamespace(time=lambda: _clk[0])
reset_guard()
c = conn()
g.save_linked_set(c, set(range(7600, 7620)))
_clk[0] += 1
g.save_linked_set(c, set(range(7601, 7620)) - {7602, 7603, 7604, 7605} | {7699})     # 5/20 → 보류
hold_t = _clk[0]
ok(pending_ids(c) == {7600, 7602, 7603, 7604, 7605}, "경계 시험 준비 — 5개 보류")
early = hold_t + 20 * 3600 - 1
_clk[0] = hold_t + 20 * 3600 + 1
g.save_linked_set(c, set(range(7606, 7620)) | {7601, 7699}, started_at=early)
ok(g.stored_linked(c, [7600]) == {7600} and 7600 in pending_ids(c),
   "20시간 1초 전에 시작한 응답은 20시간 뒤에 도착해도 해제하지 못한다(반영 시각이 아니라 받기 시작 시각)")
_clk[0] += 1
g.save_linked_set(c, set(range(7606, 7620)) | {7601, 7699})
ok(g.stored_linked(c, [7600, 7602]) == set() and pending_ids(c) == set(), "20시간이 지난 뒤 시작한 응답은 해제한다")
c.close()
g.time = _rt0

# 무작위 엇갈림 — 요청 여러 개가 겹쳐 시작·전산 읽기·반영 순서가 뒤섞여도 규칙이 깨지지 않는다(가짜 시계)
import random as _rnd   # noqa: E402
import types as _types  # noqa: E402
_real_time = g.time
HOUR = 3600.0
viol = []
runs = 0
n_held = n_confirmed = n_stale = n_straddle = n_bad = 0
for seed in range(60):
    rnd = _rnd.Random(seed)
    reset_guard()
    c = conn()
    clock = [1_000_000.0]
    g.time = _types.SimpleNamespace(time=lambda: clock[0])
    U = list(range(9000, 9040))
    truth_changes = []                     # (시각, 연결 집합)
    cur = set(rnd.sample(U, 25))
    t = clock[0]
    for _ in range(40):
        truth_changes.append((t, set(cur)))
        t += rnd.choice([60, 600, HOUR, 3 * HOUR, 8 * HOUR, 21 * HOUR])
        for _ in range(rnd.randint(0, 3)):
            i = rnd.choice(U)
            cur.symmetric_difference_update({i})

    def truth_at(x):
        st = truth_changes[0][1]
        for tt, ss in truth_changes:
            if tt <= x:
                st = ss
        return st

    end_t = t
    reqs = []
    for _ in range(70):
        s0 = rnd.uniform(clock[0], end_t)
        r0 = s0 + rnd.uniform(0, rnd.choice([1, 30, HOUR]))
        e0 = r0 + rnd.uniform(0, rnd.choice([1, 30, HOUR, 6 * HOUR]))
        seen = set(truth_at(r0))
        k = rnd.random()
        if k < 0.12:
            seen = set()                                        # 전산 오류 — 빈 목록
        elif k < 0.30:
            seen = set(rnd.sample(sorted(seen), max(0, int(len(seen) * rnd.uniform(0.4, 0.85)))))   # 일부만 옴(대량 누락)
        # 원본 응답 모양 — 번호는 숫자 글자 또는 정수, 가끔 계약 밖 값(소수·공백·너무 큰 수)이나 개수 불일치
        items = [{"logic_client_id": (str(i) if rnd.random() < 0.8 else i)} for i in sorted(seen)]
        total = len(items)
        if rnd.random() < 0.06:
            items.insert(rnd.randint(0, len(items)), {"logic_client_id": rnd.choice([3.5, " 9001", "9223372036854775808", 2 ** 63, "x", None])})
            total = len(items)
        elif rnd.random() < 0.04:
            total = len(items) + 1
        reqs.append((e0, s0, seen, items, total))
    reqs.sort(key=lambda x: x[0])
    last_present, hold_start = {}, {}
    for e0, s0, seen, items, total in reqs:
        clock[0] = e0
        before = g._stored_linked(c, U)
        pend_before = pending_ids(c)
        if not g.complete(items, total):
            n_bad += 1                      # 온전하지 않은 응답 — 지우는 쪽은 「확인 못 함」, 저장본은 그대로
            continue
        if g.ids_from_items(items) != seen:
            viol.append((seed, "온전한 응답에서 읽은 번호가 보낸 번호와 다름"))
        for i in pend_before:
            clk_i = max(hold_start.get(i, -1), last_present.get(i, -1))
            if s0 - clk_i < 20 * HOUR <= e0 - clk_i:
                n_straddle += 1
        pl = g._plan(c, seen, s0, e0)
        predicted = (set(pl["old"]) | seen) - pl["remove"]
        res = g.apply_response(c, seen, s0)
        runs += 1
        n_held += bool(res.get("held"))
        n_confirmed += res.get("reason") == "confirmed"
        n_stale += any(last_present.get(i, -1) >= s0 for i in before)
        after = g._stored_linked(c, U)
        pend_after = pending_ids(c)
        if after != predicted:
            viol.append((seed, "미리보기(같은 규칙 계산)와 실제 반영 결과가 다름"))
        removed = before - after
        if not seen <= after:
            viol.append((seed, "응답에 보인 연결이 저장되지 않음"))
        for i in removed:
            if last_present.get(i, -1) >= s0:
                viol.append((seed, f"기록 뒤에 시작하지 않은 응답이 해제 {i}"))
            if i in hold_start and s0 - max(hold_start[i], last_present.get(i, -1)) < 20 * HOUR - 1e-6:
                viol.append((seed, f"보류 시계 20시간 전에 시작한 응답이 해제 {i}"))
        if (pend_before & after) - pend_after:
            viol.append((seed, f"지우지 않은 번호의 보류가 풀림 {sorted((pend_before & after) - pend_after)[:3]}"))
        unheld = removed - pend_before
        if unheld and not seen:
            viol.append((seed, "빈 목록이 보류 없이 해제"))
        if len(before) >= 20 and len(unheld) > len(before) * 0.2:
            viol.append((seed, f"한 응답이 보류 없이 {len(unheld)}/{len(before)} 해제"))
        for i in seen:
            last_present[i] = e0
        for i in removed:
            hold_start.pop(i, None)
        for i in pend_after:
            hold_start.setdefault(i, e0)
    c.close()
g.time = _real_time
ok(n_held >= 100 and n_confirmed >= 10 and n_stale >= 100 and n_straddle >= 20 and n_bad >= 100,
   f"무작위 시험이 보류·20시간 뒤 해제·늦은 응답·20시간 경계 걸침·온전하지 않은 응답을 충분히 거쳤다"
   f"(보류 {n_held} · 해제 {n_confirmed} · 늦은 {n_stale} · 경계 {n_straddle} · 불완전 {n_bad})")
print(f"  무작위 엇갈림: 반영 {runs}회 · 보류 {n_held} · 20시간 뒤 해제 {n_confirmed} · 늦은 응답 {n_stale} · 경계 걸침 {n_straddle} · 불완전 {n_bad}")
ok(not viol, f"무작위 엇갈림 {runs}회 반영 — 규칙 위반 없음(기록 뒤 시작한 응답만 해제 · 보류는 지울 때만 풀림 · 보류 뒤 20시간 지나 시작한 응답만 해제 · 빈 목록·대량 해제 보류 · 미리보기=반영 · 원본 번호 그대로): {viol[:5]}")

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
