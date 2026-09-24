"""회귀 — 🌙 밤 재시도 상한: 밤 시간엔 오늘 2번 시도한 키워드를 다시 주지 않는다 (대표 확정 2026-09-24)

대표 원문: 「밤 재시도 횟수 상한은 하루 2번만 해.」

지키는 것:
  ① night_retry_capped — 밤(23시·0~7시) + 오늘 2번 이상이면 True · 1번이면 False · 낮(8~22시)은 몇 번이든 False
  ② attempt_count_map — 실제 원장 DDL 에 쓴 행으로: 그날 · 완료 못 한 것(projected 0) · legacy 제외만 센다 ·
     attempted_map 과 같은 키워드 집합 · 표가 없으면 빈 dict(= 거르지 않음)
  ③ /keywords 배선(소스 — 게이트에 fastapi 가 없어 import 불가):
     밤 시간에만 횟수를 세고 · 뺀 키워드는 이번 시간대·밀린 것 **둘 다**에서 빠지고 ·
     판정 실패는 거르지 않고 · 응답에 night_retry_capped 가산 · 전량 모드(구확장)는 무변경
  ④ 🔴 모의 한 밤(23시~7시) — 막히는 키워드 여럿 + 새 키워드 소수: 종전 규칙은 같은 키워드를 밤새 되풀이하고,
     새 규칙은 그날 한 키워드를 2번 넘게 주지 않는다 · 새 키워드는 하나도 안 빠진다
⚠️ stdlib 만.
"""
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


import collect_order as co  # noqa: E402
import collect_slot  # noqa: E402
import collector_observation as obs  # noqa: E402

DAY = collect_slot.DAY_HOURS

print("① night_retry_capped")
ok("상한 값은 2(대표 확정)", co.NIGHT_RETRY_DAILY_MAX == 2)
ok("낮 시간 = 8~22시(#265 와 같은 표)", tuple(DAY) == tuple(range(8, 23)))
cnt = {"두번": 2, "한번": 1, "세번": 3}
ok("🔴 밤 1시 · 오늘 2번 → 주지 않음", co.night_retry_capped("두번", cnt, 1, DAY) is True)
ok("밤 1시 · 3번 → 주지 않음", co.night_retry_capped("세번", cnt, 1, DAY) is True)
ok("🔴 밤 1시 · 1번 → 줌(두 번째 시도는 허용)", co.night_retry_capped("한번", cnt, 1, DAY) is False)
ok("밤 1시 · 오늘 처음 → 줌", co.night_retry_capped("처음", cnt, 1, DAY) is False)
ok("🔴 23시는 밤", co.night_retry_capped("두번", cnt, 23, DAY) is True)
ok("7시는 밤 · 0시는 밤", co.night_retry_capped("두번", cnt, 7, DAY) is True and co.night_retry_capped("두번", cnt, 0, DAY) is True)
ok("🔴 낮(8시·14시·22시)은 몇 번이든 줌 — 종전 그대로",
   all(co.night_retry_capped("세번", cnt, h, DAY) is False for h in (8, 14, 22)))
ok("횟수 표가 비거나 None 이면 줌(거르지 않음)",
   co.night_retry_capped("두번", {}, 1, DAY) is False and co.night_retry_capped("두번", None, 1, DAY) is False)
ok("시각이 이상하면 줌(거르지 않음)", co.night_retry_capped("두번", cnt, "x", DAY) is False)

print("\n② attempt_count_map — 실제 원장 DDL")
c = sqlite3.connect(":memory:")
obs.init_observation_db(c)
rows = [
    ("o1", "막힘", "2026-09-24", "accepted", "positive", 0),
    ("o2", "막힘", "2026-09-24", "accepted", "positive", 0),
    ("o3", "막힘", "2026-09-24", "accepted", "evidence_only", 0),
    ("o4", "완료", "2026-09-24", "accepted", "full", 1),
    ("o5", "한번", "2026-09-24", "accepted", "positive", 0),
    ("o6", "옛날", "2026-09-24", "legacy", "full", 0),
    ("o7", "막힘", "2026-09-23", "accepted", "positive", 0),
]
for oid, kw, d, st, kind, proj in rows:
    c.execute("INSERT INTO collector_observations(observation_id, keyword, collected_date, status, kind, reason, payload_hash,"
              " products_json, meta_json, projected, result_json) VALUES (?,?,?,?,?,'','h','[]','{}',?,'{}')",
              (oid, kw, d, st, kind, proj))
got = obs.attempt_count_map(c, "2026-09-24")
ok("🔴 그날 · 완료 못 한 것만 센다(막힘 3 · 한번 1)", got == {"막힘": 3, "한번": 1}, str(got))
ok("완료(projected 1)·legacy·다른 날은 안 센다", "완료" not in got and "옛날" not in got)
ok("attempted_map 과 같은 키워드 집합", set(got) == set(obs.attempted_map(c, "2026-09-24")))
ok("표가 없으면 빈 dict", obs.attempt_count_map(sqlite3.connect(":memory:"), "2026-09-24") == {})

print("\n③ /keywords 배선(소스)")
src = open(os.path.join(BACKEND, "collector.py"), encoding="utf-8").read()
m = re.search(r"def _get_collect_keywords\(.*?\n(?=def |@router)", src, re.S)
body = m.group(0) if m else ""
hourly = body[body.find("h = max(0, min(23, int(hour)))"):] if body else ""
allmode = body[body.find("if hour is None:"):body.find("h = max(0, min(23, int(hour)))")] if body else ""
ok("시간대 모드에 밤 상한 판정이 있다", "_night_capped(k, _counts, h, _DAY_HOURS)" in hourly)
ok("🔴 밤 시간일 때만 센다(if h not in _DAY_HOURS 안)", re.search(r"if h not in _DAY_HOURS:\s*\n\s*from collector_observation import attempt_count_map", hourly) is not None)
loop = hourly[hourly.find("for k, p in remaining.items():"):hourly.find("now_slot.sort(")]
ok("🔴 뺀 키워드는 루프 맨 앞에서 건너뛴다(이번 시간대·밀린 것 둘 다)",
   re.search(r"for k, p in remaining\.items\(\):\s*\n\s*if k in night_capped:\s*\n\s*continue", loop) is not None
   and loop.find("continue") < loop.find("now_slot.append") and loop.find("continue") < loop.find("overdue.append"))
ok("판정 실패는 빈 집합(거르지 않음)", re.search(r"except Exception as _ne:.*?night_capped = set\(\)", hourly, re.S) is not None)
ok("응답에 night_retry_capped 가산", '"night_retry_capped": len(night_capped)' in hourly)
ok("🔴 전량 모드(구확장)는 무변경 — 밤 상한을 안 탄다", allmode and "night_capped" not in allmode)
ok("시간당 상한·시험 상한 줄은 그대로", "picked = now_slot[:HOURLY_CAP]" in hourly and "picked = _apply_cap(picked, cap)" in hourly)

print("\n④ 🔴 모의 한 밤 — 두 대 · 기계당 시간당 15개 · 막히는 키워드 20개 + 새 키워드 소수")
NIGHT = [23] + list(range(0, 8))
CAP = 15


def simulate(use_cap):
    """시간마다 /keywords 와 같은 방식으로 고른다: 이번 시간대 → 밀린 것(시도한 것은 뒤로). 막히는 키워드는 완료되지 않는다."""
    blocked = {f"막힘{i:02d}": (i % 9) for i in range(20)}      # 밤 시간 슬롯(0~8 → 23·0~7)에 흩어 둠
    fresh = {f"새{i:02d}": (i % 9) for i in range(9)}           # 시간당 1개꼴 새 키워드(완료된다)
    slot_hour = lambda idx: NIGHT[idx]  # noqa: E731
    counts, done, handed = {}, set(), {}
    day_of = lambda hh: "D" if hh == 23 else "D+1"  # noqa: E731
    for hh in NIGHT:
        day = day_of(hh)
        dc = {k: n for (d, k), n in counts.items() if d == day}
        remaining = {k: s for k, s in list(blocked.items()) + list(fresh.items()) if (day, k) not in done}
        pos = NIGHT.index(hh)
        cands = []
        for k, s in remaining.items():
            if use_cap and co.night_retry_capped(k, dc, hh, DAY):
                continue
            sp = s
            if sp <= pos:
                cands.append(((1 if dc.get(k) else 0), 0 if sp == pos else 1, k))
        cands.sort()
        picked = [k for *_x, k in cands[:CAP * 2]]
        for k in picked:
            handed[(day, k)] = handed.get((day, k), 0) + 1
            if k in fresh:
                done.add((day, k))
            else:
                counts[(day, k)] = counts.get((day, k), 0) + 1
    return handed, done


old_h, _ = simulate(False)
new_h, new_done = simulate(True)
old_max = max(v for (d, k), v in old_h.items() if k.startswith("막힘"))
new_max = max(v for (d, k), v in new_h.items() if k.startswith("막힘"))
old_tot = sum(old_h.values()); new_tot = sum(new_h.values())
print(f"    종전: 같은 막힌 키워드 하루 최대 {old_max}번 · 밤 전체 요청 {old_tot}건 / 새 규칙: 최대 {new_max}번 · {new_tot}건")
ok("🔴 종전 규칙은 같은 키워드를 하루 3번 넘게 되풀이한다(문제 재현)", old_max >= 3, str(old_max))
ok("🔴 새 규칙은 그날 한 키워드를 2번 넘게 주지 않는다", new_max <= 2, str(new_max))
ok("🔴 새 키워드는 하나도 안 빠진다(밤새 전부 완료)", sum(1 for (d, k) in new_done if k.startswith("새")) >= 9)
ok("밤 전체 요청 수가 준다", new_tot < old_tot, f"{old_tot} → {new_tot}")

print(f"\n{'✅' if not failed else '❌'} 밤 재시도 상한 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
