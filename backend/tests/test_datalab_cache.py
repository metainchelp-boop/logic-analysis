"""회귀 — 데이터랩 결과 재사용을 일꾼 5개가 나눠 쓴다 · 24시간 (대표 확정 2026-09-23 · 결정 C)

지키는 것:
  ① datalab_cache — 넣은 값을 다시 꺼낸다 · 24시간 지나면 안 꺼낸다 · 빈값은 넣지 않는다 ·
     한글 그대로 · 7일 넘은 줄은 지운다 · DB 가 고장 나도 예외를 밖으로 안 낸다.
  ② datalab._cache_get/_cache_set — **다른 일꾼(메모리가 빈 쪽)도 보관함에서 꺼낸다** ·
     보관함에서 꺼낸 값은 **보관 시각 그대로** 메모리에 들어간다(이틀 묵은 값 방지).
  ③ analyze_datalab — 두 번째 일꾼은 네이버를 **한 번도 안 부른다** · 실패(빈값) 지표는 보관하지 않아
     다음 호출이 다시 묻는다.
  ④ 한도 소진 표시 — 한 일꾼이 받으면 다른 일꾼도 자정까지 멈춘다.
  ⑤ 재사용 기간 상수 24시간 · 플레이스 검색트렌드는 두 축이 다 찬 결과만 보관함에 굳힌다(소스).

⚠️ 실제 모듈을 임시 파일 DB 로 돌린다(가짜 흉내가 아니다). 네이버 호출 함수만 세는 가짜로 바꾼다.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

TMP = tempfile.mkdtemp(prefix="dlcache_")
os.environ["DB_PATH"] = os.path.join(TMP, "t.db")
os.environ.setdefault("NAVER_CLIENT_ID", "test-id")
os.environ.setdefault("NAVER_CLIENT_SECRET", "test-secret")

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


import datalab_cache as dc  # noqa: E402
import datalab  # noqa: E402


def fresh_worker():
    """다른 일꾼 흉내 — 그 일꾼의 메모리는 비어 있고, 한도 표시도 아직 모른다."""
    datalab._cache.clear()
    datalab._quota_block_until[0] = 0.0
    dc._quota_seen["at"] = 0.0
    dc._quota_seen["until"] = 0.0


print("== ① 보관함 자체 ==")
now = 1_800_000_000.0
ok("넣은 값을 꺼낸다(한글 그대로)",
   dc.put("k1", {"label": "여성", "ratio": 61.5}, now=now) and dc.get("k1", now=now + 60) == {"label": "여성", "ratio": 61.5})
ok("24시간 안이면 꺼낸다", dc.get("k1", now=now + 23 * 3600) is not None)
ok("24시간 지나면 안 꺼낸다", dc.get("k1", now=now + 24 * 3600) is None)
ok("빈 dict 는 넣지 않는다", dc.put("k_empty", {}, now=now) is False and dc.get("k_empty", now=now) is None)
ok("None 은 넣지 않는다", dc.put("k_none", None, now=now) is False)
v, at = dc.lookup("k1", now=now + 10)
ok("lookup 이 보관 시각을 돌려준다", at == now, f"at={at}")
dc.put("k1", {"ratio": 1}, now=now + 100)
ok("같은 키는 덮어쓴다", dc.get("k1", now=now + 101) == {"ratio": 1})
dc.put("old", {"x": 1}, now=now - 8 * 24 * 3600)
dc._last_prune[0] = 0.0
dc.put("trigger", {"x": 2}, now=now)
ok("7일 넘은 줄은 지운다", dc.lookup("old", ttl=10 ** 9, now=now)[0] is None)
ok("지우기가 방금 넣은 줄은 남긴다", dc.get("trigger", now=now) == {"x": 2})

print("== ② 일꾼 사이 나눠 쓰기 ==")
fresh_worker()
datalab._cache_set("kw|500|#gender", {"female": 70, "male": 30})
fresh_worker()   # 다른 일꾼 — 메모리 빔
ok("다른 일꾼도 보관함에서 꺼낸다", datalab._cache_get("kw|500|#gender") == {"female": 70, "male": 30})
ok("꺼낸 값이 그 일꾼 메모리에도 들어간다", "kw|500|#gender" in datalab._cache)

old = time.time() - 23 * 3600
dc.put("kw|500|#age", {"ages": [1]}, now=old)
fresh_worker()
datalab._cache_get("kw|500|#age")
ent = datalab._cache.get("kw|500|#age") or {}
ok("보관함에서 꺼낸 값은 보관 시각 그대로 메모리에 들어간다(이틀 묵은 값 방지)",
   abs(ent.get("ts", 0) - old) < 1, f"ts={ent.get('ts')} old={old}")
fresh_worker()
dc.put("kw|500|#stale", {"a": 1}, now=time.time() - 25 * 3600)
ok("보관함의 24시간 지난 값은 안 꺼낸다", datalab._cache_get("kw|500|#stale") is None)

print("== ③ analyze_datalab — 두 번째 일꾼은 네이버를 안 부른다 ==")
calls = {"gender": 0, "age": 0, "trend": 0, "weekday": 0}


def fake(name, value):
    def f(*a, **k):
        calls[name] += 1
        return value
    return f


datalab.get_gender_ratio = fake("gender", {"female": 55, "male": 45})
datalab.get_age_ratio = fake("age", {})          # 실패(빈값) — 보관하지 않아야 한다
datalab.get_trend_24m = fake("trend", {"months": [{"period": "2026-08", "ratio": 50}], "allMonths": []})
datalab.get_weekday_pattern = fake("weekday", {"days": [1, 2, 3]})
datalab.get_season_prediction = lambda t: {}
datalab.get_yoy_growth_from_trend = lambda t: {}
datalab._paced = None
_real_sleep = datalab.time.sleep
datalab.time.sleep = lambda s: None
try:
    fresh_worker()
    r1 = datalab.analyze_datalab("재사용시험키워드", "식품")
    first = dict(calls)
    fresh_worker()   # 다른 일꾼
    r2 = datalab.analyze_datalab("재사용시험키워드", "식품")
    second = {k: calls[k] - first[k] for k in calls}
finally:
    datalab.time.sleep = _real_sleep
ok("첫 일꾼은 지표마다 한 번씩 묻는다", first == {"gender": 1, "age": 1, "trend": 1, "weekday": 1}, str(first))
ok("두 번째 일꾼은 성공한 지표를 다시 묻지 않는다",
   second["gender"] == 0 and second["trend"] == 0 and second["weekday"] == 0, str(second))
ok("실패(빈값)한 지표는 보관하지 않아 다시 묻는다", second["age"] == 1, str(second))
ok("두 번째 결과도 같은 값을 준다", r2.get("gender") == r1.get("gender") and r2.get("trend") == r1.get("trend"))

print("== ④ 한도 소진 표시를 나눠 쓴다 ==")
fresh_worker()
datalab._mark_quota_exhausted()
ok("표시한 일꾼은 멈춘다", datalab.datalab_quota_exhausted())
fresh_worker()   # 다른 일꾼 — 자기 메모리엔 표시가 없다
ok("다른 일꾼도 멈춘다(보관함에서 읽음)", datalab.datalab_quota_exhausted())
dc.put(dc.QUOTA_KEY, {"until": time.time() - 5})
fresh_worker()
ok("자정이 지나면(표시 시각 지남) 다시 부른다", not datalab.datalab_quota_exhausted())

print("== ⑤ 상수 · 소스 배선 ==")
ok("재사용 기간 24시간(메모리)", datalab.CACHE_TTL == 24 * 3600, str(datalab.CACHE_TTL))
ok("재사용 기간 24시간(보관함)", dc.TTL_SECONDS == 24 * 3600)
src = open(os.path.join(BACKEND, "datalab.py"), encoding="utf-8").read()
ok("플레이스 검색트렌드는 두 축이 다 찬 것만 보관함에 굳힌다",
   '_cache_set(ck, out, shared=("months" in out and "weekdays" in out))' in src)
ok("datalab 이 보관함을 못 불러와도 돈다(import 실패 방어)", "except Exception:          # 보관함 모듈이 없어도" in src)

print("== ⑥ 보관함 고장에도 예외를 밖으로 안 낸다 ==")
os.environ["DB_PATH"] = os.path.join(TMP, "없는폴더", "x", "t.db")
try:
    a = dc.put("z", {"a": 1})
    b = dc.get("z")
    fresh_worker()
    datalab._cache_set("z2", {"a": 2})
    c = datalab._cache_get("z2")
    ok("쓰기 실패는 False · 읽기 실패는 None", a is False and b is None)
    ok("datalab 은 메모리만으로 계속 돈다", c == {"a": 2})
except Exception as e:
    ok("보관함 고장이 예외로 새지 않는다", False, repr(e))
finally:
    os.environ["DB_PATH"] = os.path.join(TMP, "t.db")

print(f"\n결과: {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
