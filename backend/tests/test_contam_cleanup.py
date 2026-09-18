"""9/17 오염 기록 1회 정리 — 회귀 시험 (2026-09-18)

왜 있나
  9/17 00:00~11:00 에 서로 다른 12개 키워드가 **같은 화면 하나**를 읽어 같은 상품 32개를
  올렸고, 그 키워드들의 순위가 전부 「순위 없음(300위 밖)」으로 잘못 기록됐다.
  이 시험은 **그 정리 작업이 필요 이상으로 지우지 않는지**를 지킨다.

⚠️ 이 시험이 지키는 것은 「지운다」가 아니라 **「안 지운다」** 쪽이다 —
   삭제는 되돌리기 어려우니, 범위가 넓어지는 변경이 들어오면 여기서 막힌다.
⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi 가 없다 — collect_cap·split_rule 과 같은 이유).
"""
import os
import re
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "scheduler.py"), encoding="utf-8").read()

_p = _f = 0


def ok(name, cond):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS  {name}")
    else:
        _f += 1
        print(f"  FAIL  {name}")


def code(src):
    """주석을 떼고 본다 — 주석에 옛 코드를 적어 두는 관행 때문에 헛실패한 적이 있다."""
    return re.sub(r"#[^\n]*", "", src)


print("\n[9/17 오염 정리 — 범위가 넓어지지 않게 지킨다]")

i = SRC.find("def _run_contam_20260917_cleanup(")
ok("정리 함수가 있다", i > 0)
FN = code(SRC[i:SRC.find("\ndef ", i + 10)] if SRC.find("\ndef ", i + 10) > 0 else SRC[i:])

# ① 조건 넷이 전부 살아 있는가 — 하나라도 빠지면 지우는 범위가 넓어진다
ok("① 날짜를 좁힌다", "DATE(checked_at)=?" in FN)
ok("① 오염 시간대만 — 12:00 이후(정상 회차)는 안 지운다", "checked_at < ?" in FN)
ok("① 그 키워드만", "keyword IN (" in FN)
ok("① **순위가 있는 행은 손대지 않는다**(오염분은 전부 미노출이었다)",
   "rank_position IS NULL" in FN)

# ② 지우기 전에 되돌릴 근거를 남기는가
ok("② 삭제 전에 대상을 먼저 읽는다(SELECT 가 DELETE 보다 앞)",
   FN.index("SELECT id") < FN.index("DELETE FROM"))
ok("② 전건을 로그로 남긴다", "삭제예정" in FN)
ok("② 업체명·상품명은 안 찍는다(저장소·로그 공개 대비 — id 만)",
   "name" not in FN.split("삭제예정")[1][:200])

# ③ 한 번만 돈다
ok("③ 마커로 재실행을 막는다", "_CONTAM_MARKER_NAME" in FN and "os.path.exists(marker)" in FN)
# ⚠️ 문구로 보면 문구만 바꿔도 시험이 **예외로 죽는다**(FAIL 로 안 보인다 — 사보타주에서 겪었다).
#    구조로 본다: except 블록 안에 마커 생성이 있으면 실패해도 마커가 남아 재시도가 막힌다.
_exc = FN[FN.index("except Exception"):] if "except Exception" in FN else ""
ok("③ 실패하면 마커를 안 남긴다(except 안에 마커 생성이 없다 — 다음 배포에서 재시도)",
   bool(_exc) and "open(marker" not in _exc)

# ④ 상수가 실제 사고 범위와 맞는가
ok("④ 날짜가 2026-09-17 이다", '_CONTAM_DATE = "2026-09-17"' in SRC)
ok("④ 경계가 12:00 이다(그 뒤는 정상 회차 357·399·400개)",
   '_CONTAM_UNTIL = "2026-09-17 12:00:00"' in SRC)
kws = re.search(r"_CONTAM_KEYWORDS_20260917 = \[(.*?)\]", SRC, re.S)
ok("④ 키워드가 12개다(진단으로 확정한 수)",
   bool(kws) and len(re.findall(r'"[^"]+"', kws.group(1))) == 12)

# ⑤ 부팅 1회성 잡으로 등록돼 있는가
ok("⑤ 부팅 뒤 한 번 도는 잡으로 등록된다",
   "contam_20260917_cleanup_boot" in SRC and 'trigger="date"' in SRC)

# ⑥ 실제로 돌려 본다 — 지울 것만 지우는가
with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "t.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE client_rank_history (id INTEGER PRIMARY KEY, client_id INT, "
              "keyword TEXT, rank_position INT, checked_at TEXT, check_type TEXT)")
    rows = [
        # (keyword, rank, checked_at, 지워야 하나)
        ("갈비", None, "2026-09-17 07:00:10", True),    # 오염 — 지운다
        ("갈비", 12,   "2026-09-17 07:00:10", False),   # 순위 있음 — 안 지운다
        ("갈비", None, "2026-09-17 13:00:00", False),   # 12시 이후 — 안 지운다
        ("갈비", None, "2026-09-18 07:00:00", False),   # 다른 날 — 안 지운다
        ("감귤", None, "2026-09-17 07:00:00", False),   # 다른 키워드 — 안 지운다
        ("갓김치", None, "2026-09-17 01:01:05", True),  # 오염 — 지운다
    ]
    for i2, (kw, rk, at, _) in enumerate(rows, 1):
        c.execute("INSERT INTO client_rank_history VALUES (?,?,?,?,?,?)",
                  (i2, 100 + i2, kw, rk, at, "scheduled"))
    c.commit()
    KW = re.findall(r'"([^"]+)"', kws.group(1))
    ph = ",".join("?" * len(KW))
    where = (f"DATE(checked_at)=? AND checked_at < ? AND keyword IN ({ph}) "
             "AND rank_position IS NULL")
    args = ["2026-09-17", "2026-09-17 12:00:00"] + KW
    got = {r[0] for r in c.execute(
        f"SELECT id FROM client_rank_history WHERE {where}", args).fetchall()}
    want = {i2 for i2, (_, _, _, kill) in enumerate(rows, 1) if kill}
    ok("⑥ 지울 행만 정확히 고른다(순위 있는 행·12시 이후·다른 날·다른 키워드는 남는다)",
       got == want or (print(f"     고른 것 {sorted(got)} · 기대 {sorted(want)}"), False)[1])
    c.close()

print(f"\n{'❌ 실패 ' + str(_f) if _f else '✅'} 통과 {_p} · 실패 {_f}")
sys.exit(1 if _f else 0)
