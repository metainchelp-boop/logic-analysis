"""회귀 — 소상공인365 분류표·통계 API 가 막혔을 때 (2026-11-28)

왜 만들었나
  11/27 배포(#377)가 캐시 판을 v4 로 올리면서 30일 동안 쓸 수 있던 업종 분류표 저장본까지 지웠다.
  바로 그날 밤 소상공인365 의 분류표·통계 API(/gis/…)가 503 으로 막혀 분류표를 다시 받지 못했고,
  업종 13종이 하나도 이어지지 않았다. 화면은 기관 장애인데도 「고른 업종에 맞는 상권 분류를 찾지 못했다 ·
  다른 업종으로 다시」라고 안내했고, 05:00 업종 사전 점검은 분류표를 못 받으면 조용했다.

지키는 것
  ① 분류표 저장본은 캐시 판과 따로 둔다 — 판 정리가 분류표를 지우지 않는다.
  ② 분류표: 30일 안 저장본 → 새로 받기 → 지난 저장본 → 내장 사본. 받기에 실패하면 10분은 다시 부르지 않는다.
  ③ 내장 사본만으로도 업종 13종이 전부 이어진다.
  ④ 분류표가 아예 없으면 industry-unmapped 가 아니라 error(잠시 후 다시)로 알린다.
  ⑤ 통계 API 의 502·503·504·연결 실패는 「집계 없음(no-stats)」이 아니라 error 다. 500 은 평상시에도 오므로(틀린 지역 표기) 장애로 세지 않는다.
  ⑥ 실패 로그에 인증키가 찍히지 않는다(예외 문구에 주소가 통째로 들어 있어도).
  ⑦ 05:00 업종 사전 점검이 「판정 못 함」·「지난 저장본·내장 사본으로 판정」을 경고 한 줄로 남긴다.

네트워크 0 — HTTP 함수와 requests.get 을 가짜로 바꿔 놓고 돌린다. DB 는 임시 파일.
"""
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

TMP = tempfile.mkdtemp(prefix="sbiz-tree-")
os.environ["DB_PATH"] = os.path.join(TMP, "t.db")
os.environ["SBIZ365_KEY_SIMPLE"] = "TESTKEY-DO-NOT-LOG-123"

import database        # noqa: E402
database.DB_PATH = os.environ["DB_PATH"]
import requests        # noqa: E402
import sbiz365 as sb   # noqa: E402
import sbiz_health     # noqa: E402

passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  ✗", msg)


FIXTURE = [tuple(line.rstrip("\n").split("\t", 1))
           for line in open(os.path.join(HERE, "fixtures", "sbiz_upjong_tree.tsv"), encoding="utf-8") if "\t" in line]
REAL_HTTP = sb._http_json
REAL_SNAPSHOT_PATH = sb.TREE_SNAPSHOT_PATH


def conn():
    return database._get_conn()


def put(key, pairs, days_ago=0):
    c = conn()
    c.execute("CREATE TABLE IF NOT EXISTS sbiz_cache (cache_key TEXT PRIMARY KEY, payload TEXT, fetched_at TEXT)")
    c.execute("INSERT OR REPLACE INTO sbiz_cache VALUES (?,?,?)",
              (key, json.dumps([list(p) for p in pairs], ensure_ascii=False),
               (datetime.now() - timedelta(days=days_ago)).isoformat()))
    c.commit()
    c.close()


def keys():
    c = conn()
    out = sorted(r[0] for r in c.execute("SELECT cache_key FROM sbiz_cache"))
    c.close()
    return out


def reset(snapshot=True):
    c = conn()
    c.execute("CREATE TABLE IF NOT EXISTS sbiz_cache (cache_key TEXT PRIMARY KEY, payload TEXT, fetched_at TEXT)")
    c.execute("DELETE FROM sbiz_cache")
    c.commit()
    c.close()
    sb._cache_table_ready = True
    sb._tree_state.update(source=None, fetched_at=None, failed_at=0.0)
    sb._tree_snapshot_pairs = None
    sb.TREE_SNAPSHOT_PATH = REAL_SNAPSHOT_PATH if snapshot else os.path.join(TMP, "없는-사본.tsv")
    sb._last_outage_at = 0.0
    sb._http_json = REAL_HTTP


calls = []


def fake_http(result=None, outage=False):
    def f(method, url, params=None, data=None):
        calls.append(url)
        if outage:
            sb._mark_outage()
        return result
    return f


TREE_JSON = [{"upjong3cd": c, "upjong3nm": n} for c, n in FIXTURE]
OLD = FIXTURE[:5]

# ① 판 정리가 분류표 저장본을 지우지 않는다
reset()
for k in ("v3:sbiz:simple:x", "v4:sbiz:simple:y"):
    put(k, OLD)
put("v3:sbiz:upjong-tree", OLD)
put(sb.TREE_CACHE_KEY, OLD)
sb._cache_table_ready = False
sb._cache_conn().close()
ok(keys() == sorted([sb.TREE_CACHE_KEY, "v3:sbiz:upjong-tree", "v4:sbiz:simple:y"]),
   f"판 정리는 옛 판 상권 결과만 지우고 분류표 저장본은 남긴다: {keys()}")

# ② 30일 안 저장본이면 API 를 부르지 않는다
reset()
put(sb.TREE_CACHE_KEY, FIXTURE, days_ago=3)
calls.clear()
sb._http_json = fake_http(TREE_JSON)
ok(sb._upjong_pairs() == FIXTURE and not calls and sb.upjong_tree_status()["source"] == "cache",
   "30일 안 저장본 → 그대로 · 분류표 API 호출 0")

# 옛 판 키(…:sbiz:upjong-tree)만 있어도 읽는다 — 배포 전에 지금 코드가 다시 받아 둔 저장본
reset()
put("v4:sbiz:upjong-tree", FIXTURE, days_ago=1)
calls.clear()
sb._http_json = fake_http(TREE_JSON)
ok(sb._upjong_pairs() == FIXTURE and not calls, "옛 판 키의 분류표 저장본도 읽는다")

# 30일 지난 저장본 + 받기 성공 → 새것으로 바꿔 저장
reset()
put(sb.TREE_CACHE_KEY, OLD, days_ago=40)
calls.clear()
sb._http_json = fake_http(TREE_JSON)
got = sb._upjong_pairs()
ok(got == FIXTURE and len(calls) == 1 and sb.upjong_tree_status()["source"] == "live", "30일 지나면 새로 받아 쓴다")
c = conn()
row = c.execute("SELECT payload, fetched_at FROM sbiz_cache WHERE cache_key=?", (sb.TREE_CACHE_KEY,)).fetchone()
c.close()
ok(row is not None and len(json.loads(row[0])) == len(FIXTURE)
   and (datetime.now() - datetime.fromisoformat(row[1])).total_seconds() < 60, "새로 받은 분류표를 저장한다")

# 30일 지난 저장본 + 받기 실패 → 지난 저장본 · 10분은 다시 부르지 않는다
reset()
put(sb.TREE_CACHE_KEY, FIXTURE, days_ago=40)
calls.clear()
sb._http_json = fake_http(None, outage=True)
ok(sb._upjong_pairs() == FIXTURE and len(calls) == 1 and sb.upjong_tree_status()["source"] == "stale",
   "받기 실패 → 30일 지난 저장본으로 잇는다")
ok(sb.upjong_tree_status()["fetched_at"] is not None, "지난 저장본이면 받은 때를 알려 준다")
sb._upjong_pairs()
sb._upjong_pairs()
ok(len(calls) == 1, f"받기 실패 뒤 10분은 분류표 API 를 다시 부르지 않는다: {len(calls)}회")
sb._tree_state["failed_at"] -= sb.TREE_RETRY_AFTER + 1
sb._upjong_pairs()
ok(len(calls) == 2, "10분이 지나면 다시 받아 본다")

# ③ 저장본이 없고 받기도 실패 → 내장 사본 · 13종 전부 이어진다
reset()
calls.clear()
sb._http_json = fake_http(None, outage=True)
snap = sb._upjong_pairs()
ok(snap is not None and len(snap) == 247 and sb.upjong_tree_status()["source"] == "snapshot", "저장본도 없으면 내장 사본")
ok(sb.unmapped_industry_labels() == [], f"내장 사본만으로 업종 13종이 전부 이어진다: {sb.unmapped_industry_labels()}")
ok(open(sb.TREE_SNAPSHOT_PATH, encoding="utf-8").read()
   == open(os.path.join(HERE, "fixtures", "sbiz_upjong_tree.tsv"), encoding="utf-8").read(),
   "내장 사본 = 시험용 분류표 사본(둘이 어긋나지 않게)")
ok(not sb.TREE_SNAPSHOT_PATH.replace("\\", "/").split("/backend/")[-1].startswith("data/"),
   "내장 사본은 DB 볼륨(/app/data)이 덮는 자리에 두지 않는다")

# ④ 분류표가 아예 없으면 industry-unmapped 가 아니라 error
ADMI = {"admiCd": "1100000000", "admiNm": "가동", "guNm": "가구", "sidoNm": "서울특별시", "scope": "dong"}
sb._resolve_admi = lambda region, biz_name="": dict(ADMI)
reset(snapshot=False)
calls.clear()
sb._http_json = fake_http(None, outage=True)
why = {}
ok(sb._get_place_sbiz_impl("가동", "카페·디저트", reason=why) is None and why.get("code") == "error",
   f"분류표가 아예 없으면 error(잠시 후 다시): {why}")

# 분류표는 있는데 사전이 어긋난 업종 → 종전대로 industry-unmapped
reset()
put(sb.TREE_CACHE_KEY, [("Z00001", "기타 > 아무거나 > 무관한 분류")], days_ago=1)
sb._http_json = fake_http(None)
why = {}
sb._get_place_sbiz_impl("가동", "베이커리·제과", reason=why)
ok(why.get("code") == "industry-unmapped", f"분류표가 있는데 못 이으면 industry-unmapped 그대로: {why}")

# ⑤ 통계 API 장애(503) → error · 500 만 → no-stats
reset()
put(sb.TREE_CACHE_KEY, FIXTURE, days_ago=1)
sb._http_json = fake_http(None, outage=True)
why = {}
ok(sb._get_place_sbiz_impl("가동", "카페·디저트", reason=why) is None and why.get("code") == "error",
   f"통계 API 503 → error: {why}")
reset()
put(sb.TREE_CACHE_KEY, FIXTURE, days_ago=1)
sb._http_json = fake_http(None, outage=False)
why = {}
ok(sb._get_place_sbiz_impl("가동", "카페·디저트", reason=why) is None and why.get("code") == "no-stats",
   f"장애 신호 없이 응답이 없으면 종전대로 no-stats: {why}")


# 진짜 HTTP 함수가 장애 신호를 남기는지 — requests.get 만 가짜로
class _Resp:
    def __init__(self, code):
        self.status_code = code

    def json(self):
        return {}


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


cap = _Cap()
sb.logger.addHandler(cap)
real_get = sb.requests.get
try:
    for code, want in ((503, True), (502, True), (504, True), (500, False), (404, False)):
        reset()
        sb.requests.get = lambda *a, _c=code, **k: _Resp(_c)
        t0 = __import__("time").monotonic()
        sb._http_json("GET", sb._BASE + "/gis/x", params={"certKey": os.environ["SBIZ365_KEY_SIMPLE"]})
        ok(sb._outage_since(t0) is want, f"HTTP {code} → 장애 신호 {want}")
    for exc in (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
        reset()

        def boom(*a, _e=exc, **k):
            raise _e("HTTPSConnectionPool: /gis/x?certKey=" + os.environ["SBIZ365_KEY_SIMPLE"])

        sb.requests.get = boom
        t0 = __import__("time").monotonic()
        sb._http_json("GET", sb._BASE + "/gis/x", params={"certKey": os.environ["SBIZ365_KEY_SIMPLE"]})
        ok(sb._outage_since(t0), f"{exc.__name__} → 장애 신호")
    reset()
    sb.requests.get = lambda *a, **k: (_ for _ in ()).throw(ValueError("Expecting value"))
    t0 = __import__("time").monotonic()
    sb._http_json("GET", sb._BASE + "/gis/x")
    ok(not sb._outage_since(t0), "응답 해석 실패는 장애로 세지 않는다")
finally:
    sb.requests.get = real_get
    sb.logger.removeHandler(cap)
ok(cap.msgs and not any(os.environ["SBIZ365_KEY_SIMPLE"] in m for m in cap.msgs),
   "실패 로그에 인증키가 찍히지 않는다")


# ⑦ 05:00 업종 사전 점검 — 판정 못 함 · 지난 저장본 · 내장 사본이면 경고 한 줄
class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, msg):
        self.lines.append(msg)


reset()
put(sb.TREE_CACHE_KEY, FIXTURE, days_ago=1)
lg = _Log()
ok(sbiz_health.check_industry_map(lg) == [] and not lg.lines, "30일 안 저장본으로 판정했고 어긋난 업종이 없으면 경고 없음")
reset()
put(sb.TREE_CACHE_KEY, FIXTURE, days_ago=40)
sb._http_json = fake_http(None, outage=True)
lg = _Log()
ok(sbiz_health.check_industry_map(lg) == [] and len(lg.lines) == 1 and "지난 저장본" in lg.lines[0],
   f"지난 저장본으로 판정했으면 경고 한 줄: {lg.lines}")
reset()
sb._http_json = fake_http(None, outage=True)
lg = _Log()
ok(sbiz_health.check_industry_map(lg) == [] and len(lg.lines) == 1 and "내장 사본" in lg.lines[0],
   f"내장 사본으로 판정했으면 경고 한 줄: {lg.lines}")
reset(snapshot=False)
sb._http_json = fake_http(None, outage=True)
lg = _Log()
ok(sbiz_health.check_industry_map(lg) is None and len(lg.lines) == 1 and "판정하지 못했다" in lg.lines[0],
   f"분류표가 아예 없으면 None + 경고 한 줄: {lg.lines}")

reset()
print(f"sbiz_tree_fallback: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
