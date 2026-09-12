"""막힘 보고 — 회귀 시험 (2026-09-12)

무엇을 막는가: 2026-09-09~11 에 수집이 멈췄는데 **무엇에 막혔는지를 서버가 몰랐다.**
증거가 맥미니 팝업에만 남아, 사람이 그 칸을 열어 읽어 주기 전에는
「IP 차단」인지 「확장 감지」인지 가릴 수 없었다. 사흘을 그렇게 썼다.

⚠️ 표준 라이브러리만 쓴다(게이트에 fastapi 가 없다) — DDL 과 자르기 규칙을 소스에서 떼어 검사한다.
"""
import ast
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(os.path.dirname(HERE), "collector.py"), encoding="utf-8").read()

_pass = _fail = 0


def ok(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}")


print("\n[막힘 보고]")

# ① 표 DDL 이 실제로 도는가 — 소스에서 떼어 진짜 sqlite 에 걸어 본다
m = re.search(r"CREATE TABLE IF NOT EXISTS collector_blocks \(.*?\);", SRC, re.S)
ok("① collector_blocks DDL 이 있다", m is not None)
if m:
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(m.group(0))
        cols = [c[1] for c in conn.execute("PRAGMA table_info(collector_blocks)").fetchall()]
        ok("① 진짜 sqlite 에 걸린다", "id" in cols)
        for need in ("at", "keyword", "err", "title", "href", "body", "ext_version"):
            ok(f"① 칸 `{need}` 이 있다", need in cols)
        # 실제로 한 줄 넣고 읽힌다
        conn.execute("INSERT INTO collector_blocks(keyword, err, title) VALUES('김치','BLOCK_TEXT','x')")
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM collector_blocks").fetchone()[0]
        ok("① 넣고 읽힌다", n == 1)
    finally:
        conn.close()
        try:
            os.unlink(db)
        except OSError:
            pass

# ② 엔드포인트가 있고 토큰을 검사한다
tree = ast.parse(SRC)
fn = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "report_blocked":
        fn = node
seg = ast.get_source_segment(SRC, fn) if fn else ""
ok("② report_blocked 가 있다", fn is not None)
ok("② 토큰을 검사한다", "_auth(x_collector_token)" in seg)
ok("② /blocked 경로에 걸려 있다", '@router.post("/blocked")' in SRC)

# ③ 저장할 때 **자른다** — 원문을 통째로 쌓지 않는다
ok("③ 본문을 500자로 자른다", "(req.body or \"\")[:500]" in seg)
ok("③ 제목을 200자로 자른다", "(req.title or \"\")[:200]" in seg)
ok("③ 주소를 500자로 자른다", "(req.href or \"\")[:500]" in seg)

# ④ 로그로도 남는다 — 표를 안 열어도 눈에 띄게
ok("④ 서버 로그에 남긴다", "막힘 보고" in seg)

# ⑤ 🔴 확장 쪽 — 보고가 수집을 넘어뜨리면 안 된다
BG = open(os.path.join(os.path.dirname(os.path.dirname(HERE)),
                       "collector-extension", "background.js"), encoding="utf-8").read()
i = BG.find("async function reportBlocked(")
rb = BG[i:BG.find("\n}\n", i)] if i >= 0 else ""
ok("⑤ 확장에 reportBlocked 가 있다", i >= 0)
ok("⑤ 예외를 밖으로 내지 않는다", "catch (e) { /* 보고 실패는 무시한다" in rb)
ok("⑤ 토큰이 없으면 보내지 않는다", "if (!token) return;" in rb)
ok("⑤ 확장 버전을 함께 보낸다", "extVersion" in rb)

# ⑥ 세 자리에서 부른다 — 차단문구 · 주소이탈 · 판독실패
ok("⑥ 차단 문구에서 보고한다", "note: '차단 문구'" in BG)
ok("⑥ 주소 이탈에서 보고한다", "note: '주소 이탈'" in BG)
ok("⑥ 판독 실패에서도 보고한다", "note: '판독 실패(차단 아님)'" in BG)
ok("⑥ 「막힘」과 「못 읽음」을 섞지 않는다", BG.count("차단 아님") >= 1)

print("\n" + (f"❌ 실패 {_fail}건 / 전체 {_pass + _fail}" if _fail else "막힘 보고 시험 전부 통과"))
sys.exit(1 if _fail else 0)
