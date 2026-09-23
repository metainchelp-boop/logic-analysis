"""회귀 — 신고 #275 (2026-09-23) 분석 화면 「순위 추적」 버튼이 nvMid 때문에 죽던 것

무엇이 있었나
  9/18 에 서버가 `nv_mid` 를 **필수**로 받게 바뀌었다(대표 확정 「새 등록은 nvMid 필수」).
  순위 추적 탭에는 칸을 붙였는데 분석 결과 화면의 형제 버튼(`TrackRegisterButton`)은 빠뜨렸다.
  실측 — 9/18 이후 그 버튼 성공 0건 · 400 10건(9/22 7 · 9/23 3), 응답 303바이트 = 전부
  「nvMid 를 넣어야 등록됩니다」. 신고 #266(client_id)과 **같은 모양의 두 번째 사고**다.

지키는 것
  ① `nvmid.existing_for` — 이 요청이 **고칠 행**(같은 주소·같은 직원)의 저장된 nvMid 만 빌린다.
     다른 직원 행·주소 모양이 다른 행·비었거나 모양이 틀린 값은 빌리지 않는다.
  ② 서버 배선 — nvMid 없는 요청은 그 행에 값이 있을 때만 받고, **새 상품은 종전대로 400**.
  ③ 두 곳의 「같은 행」 기준이 갈라지지 않는다(`add_tracked_product` 와 `existing_for`).
  ④ 화면 배선 — 이미 추적 중이면 저장된 nvMid 를 보내고, 없으면 칸·🔎 자동 찾기를 보인다.
     상한 5개·자릿수 8~20 이 서버 값과 같다. 훅은 조기 반환 앞에 있다.

⚠️ 표준 라이브러리만 — 배포 게이트에 fastapi 가 없다. ①③은 실제 모듈·가짜 DB, ②④는 소스 배선.
⚠️ 실제 React 렌더 시험(시나리오 9종 · 34항)은 PR 검증에서 따로 돌렸다(게이트 환경에 react 없음).
"""
import ast
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def func_src(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or "", node
    return "", None


import nvmid
import keyword_limit

# ─────────────────────────────────────────────────────────────
print("① nvmid.existing_for — 가짜 DB")
c = sqlite3.connect(":memory:")
c.executescript("""
CREATE TABLE tracked_products (id INTEGER PRIMARY KEY AUTOINCREMENT, product_url TEXT NOT NULL,
  product_id TEXT DEFAULT '', user_id INTEGER DEFAULT 0, nv_mid TEXT DEFAULT '', disabled_at TEXT DEFAULT '');
""")
U = "https://smartstore.naver.com/shopA/products/1234567890"
c.execute("INSERT INTO tracked_products(product_url,product_id,user_id,nv_mid) VALUES(?,?,?,?)", (U, "1234567890", 4, "87654321012"))
c.execute("INSERT INTO tracked_products(product_url,product_id,user_id,nv_mid) VALUES(?,?,?,?)", (U + "?NaPm=x", "1234567890", 5, "81111111111"))
c.execute("INSERT INTO tracked_products(product_url,user_id,nv_mid) VALUES(?,?,?)", ("https://e/empty", 4, ""))
c.execute("INSERT INTO tracked_products(product_url,user_id,nv_mid) VALUES(?,?,?)", ("https://e/short", 4, "12345"))
c.execute("INSERT INTO tracked_products(product_url,user_id,nv_mid) VALUES(?,?,?)", ("https://e/urlform", 4, "https://search.shopping.naver.com/x?nvMid=82222222222&a=1"))
c.execute("INSERT INTO tracked_products(product_url,user_id,nv_mid,disabled_at) VALUES(?,?,?,?)", ("https://e/off", 4, "83333333333", "2026-09-22 10:36:00"))
c.commit()
ok("같은 주소·같은 직원 → 저장된 nvMid", nvmid.existing_for(c, U, 4) == "87654321012")
ok("같은 주소라도 **다른 직원** 행은 빌리지 않는다", nvmid.existing_for(c, U, 5) == "")
ok("주소 모양이 다르면(쿼리 붙음) 빌리지 않는다 — 그건 add_tracked_product 가 새 행으로 만드는 등록이다",
   nvmid.existing_for(c, U + "?NaPm=x", 4) == "")
ok("저장값이 비었으면 \"\"", nvmid.existing_for(c, "https://e/empty", 4) == "")
ok("저장값 모양이 틀리면(5자리) \"\" — 틀린 옛 값을 빌려 쓰지 않는다", nvmid.existing_for(c, "https://e/short", 4) == "")
ok("저장값이 주소형이면 숫자만 뽑아 쓴다", nvmid.existing_for(c, "https://e/urlform", 4) == "82222222222")
ok("내려 둔(9/22 정리) 같은 행은 빌린다 — 같은 직원이 같은 상품을 다시 올리는 재등록이다",
   nvmid.existing_for(c, "https://e/off", 4) == "83333333333")
ok("없는 주소 → \"\"", nvmid.existing_for(c, "https://e/none", 4) == "")
ok("주소가 비었거나 문자열이 아니면 \"\"", nvmid.existing_for(c, "", 4) == "" and nvmid.existing_for(c, None, 4) == "")
c2 = sqlite3.connect(":memory:")
c2.execute("CREATE TABLE tracked_products (id INTEGER PRIMARY KEY, product_url TEXT, user_id INTEGER)")
c2.execute("INSERT INTO tracked_products(product_url,user_id) VALUES(?,?)", (U, 4))
ok("nv_mid 칸이 없는 옛 표에서도 죽지 않고 \"\"(→ 호출처는 종전대로 거절)", nvmid.existing_for(c2, U, 4) == "")

# ─────────────────────────────────────────────────────────────
print("② 서버 배선 — main.track_product")
main_src = read("backend/main.py")
fn, node = func_src(main_src, "track_product")
ok("track_product 를 찾았다", bool(fn))
# ⚠️ 서버는 `existing_for` 를 `_nv_existing` 로 불러 쓴다 — 이름이 아니라 **호출 모양**으로 찾는다
m_fb = re.search(r"from nvmid import existing_for as (\w+)[\s\S]*?\b\1\(", fn)
i_fb = m_fb.end() if m_fb else -1
i_raise = fn.find("nvMid(네이버 쇼핑 상품번호)를 넣어야 등록됩니다")
ok("🔴 nvMid 가 없을 때 거절하기 **전에** 저장된 nvMid 를 찾는다", 0 <= i_fb < i_raise, f"fb={i_fb} raise={i_raise}")
ok("🔴 찾는 기준 = 이 요청의 주소 + 로그인한 직원",
   re.search(r"existing\w*\(\s*_nvc\s*,\s*req\.product_url\s*,\s*current_user\[\"id\"\]\s*\)", fn) is not None)
ok("🔴 새 상품은 여전히 400 — 거절 문구가 남아 있다(대표 확정 ③)", i_raise > 0 and "status_code=400" in fn[i_raise - 300:i_raise])
# 폴백은 요청에 nvMid 가 **없을 때만** — 요청 값이 있으면 그 값이 우선이다
guard = re.search(r"_nv = _nv_norm\(req\.nv_mid\)\s*\n\s*_nv_source = \"request\" if _nv else \"\"\s*\n\s*if not _nv:", fn)
ok("폴백은 요청에 nvMid 가 없을 때만 돈다(요청 값이 우선)", guard is not None)
ok("조회가 실패하면 빈 값 → 종전대로 거절(fail-closed)", re.search(r"except Exception as _nve:[\s\S]{0,200}_nv = \"\"", fn) is not None)
ok("응답에 nv_mid_source 가산(request/existing)", "\"nv_mid_source\": _nv_source" in fn)
ok("모양 검사(is_valid)는 그대로 남아 있다", "_nv_ok(_nv)" in fn and "nvMid 모양이 맞지 않습니다" in fn)

# ─────────────────────────────────────────────────────────────
print("③ 「같은 행」 기준이 두 곳에서 같다")
db_src = read("backend/database.py")
add_fn, _ = func_src(db_src, "add_tracked_product")
nv_src = read("backend/nvmid.py")
ex_fn, _ = func_src(nv_src, "existing_for")
pat = "WHERE product_url = ? AND user_id = ?"
ok("add_tracked_product 가 고칠 행을 「주소 + 직원」으로 찾는다", pat in add_fn)
ok("existing_for 도 **똑같은** 기준으로 찾는다(갈라지면 A 행 번호로 B 행을 새로 만든다)", pat in ex_fn)

# ─────────────────────────────────────────────────────────────
print("④ 화면 배선 — TrackRegisterButton")
trb = read("frontend/js/components/TrackRegisterButton.jsx")
call = trb[trb.find("api.post('/products/track'"):]
call = call[:call.find("})") + 2]
ok("🔴 /products/track 에 nv_mid 를 보낸다", re.search(r"\bnv_mid\s*:\s*sendNv\b", call) is not None, call[:200])
ok("🔴 이미 추적 중이면 그 상품의 저장된 nvMid 를 쓴다(다시 넣게 하지 않는다)",
   re.search(r"knownNv\s*=\s*\(already && nvOk\(already\.nv_mid\)\)", trb) is not None)
ok("저장된 번호가 없을 때만 칸을 보인다", re.search(r"function nvField\(\)\s*\{\s*if \(!needNv\) return null;", trb) is not None)
ok("🔎 자동 찾기는 수집분 조회 경로(네이버 요청 0건)를 쓴다", "api.post('/products/nvmid-lookup'" in trb)
ok("nvMid 없이 누르면 보내지 않고 이유를 말한다", re.search(r"if \(!sendNv\) \{ setErr\(", trb) is not None)
ok("버튼 잠금이 업체+nvMid 둘 다를 본다", "var ready = !!(client && sendNv) && !adding;" in trb)
ok("서버가 상한으로 거절한 키워드(keywords_rejected)를 성공으로 알리지 않는다",
   "keywords_rejected" in trb and "추가되지 않았습니다" in trb)
m_kw = re.search(r"var KW_MAX = (\d+);", trb)
ok("상한 = 서버 keyword_limit.MAX_MANUAL_KEYWORDS", bool(m_kw) and int(m_kw.group(1)) == keyword_limit.MAX_MANUAL_KEYWORDS,
   f"화면 {m_kw and m_kw.group(1)} · 서버 {keyword_limit.MAX_MANUAL_KEYWORDS}")
m_nv = re.search(r"var NV_MIN = (\d+), NV_MAX = (\d+);", trb)
ok("자릿수 범위 = 서버 nvmid.MIN_LEN·MAX_LEN", bool(m_nv) and (int(m_nv.group(1)), int(m_nv.group(2))) == (nvmid.MIN_LEN, nvmid.MAX_LEN))
early = trb.find("if (!searchedProductUrl || !searchedKeyword || !canEdit) return null;")
hooks = [m.start() for m in re.finditer(r"React\.use(State|Effect)\(", trb)]
ok("🔴 훅이 전부 조기 반환 **앞**에 있다(2026-09-15 화면 로드 오류와 같은 함정)",
   early > 0 and hooks and max(hooks) < early, f"early={early} last_hook={max(hooks) if hooks else None}")
ok("다른 상품을 분석하면 넣어 둔 nvMid 를 비운다", re.search(r"React\.useEffect\(function\(\) \{ setNvInput\(''\); setNvMsg\(null\); \}, \[searchedProductUrl\]\);", trb) is not None)

# ─────────────────────────────────────────────────────────────
print("⑤ 9/22 실제 모양 — 5개 찬 상품에 여섯 번째 키워드")
ok("서버는 5개 찬 상품에 1개를 더 받지 않는다", keyword_limit.can_add(5, 1) is False)
ok("화면의 상한 판정(키워드 수 ≥ KW_MAX)이 같은 곳에서 멈춘다", bool(m_kw) and 5 >= int(m_kw.group(1)))

print(f"\n{'✅' if not failed else '🔴'} 신고 #275 회귀 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
