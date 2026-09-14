"""업체 피커·추적 등록 회귀 시험 (2026-09-14 · 신고 #265 #266)

무엇을 막는가 — 세 가지다.

① **업체 없이 등록을 보내는 버튼**(신고 #266).
   2026-08-28 에 `track_product` 가 `client_id` 를 **필수**로 바꿨다(없으면 400).
   그때 등록 버튼 하나(`RankTrackingSection`)는 고쳤는데 **같은 화면의 형제
   `TrackRegisterButton` 을 빠뜨렸다.** 그 버튼은 8/28~9/14 **17일 동안 누를 때마다 400**
   이었고, 아무도 몰랐다(9/14 실측: 400 10건 · 200 6건).
   ⇒ **화면에서 `/products/track` 를 부르는 자리는 전부 `client_id` 를 함께 보내야 한다.**
      새 버튼을 만들어도 이 시험이 잡는다.

② **관리팀이 남의 업체를 못 보던 것**(신고 #265, 대표 확정 「모두 보게 하자」).
   `registered-clients` 가 manager 에게 `created_by = 본인` 으로 좁혀 줬는데
   주인 없는 광고주가 **0곳**이라, 실측하니 manager 12명 중 **4명은 0~1곳**만 보였다.
   ⇒ manager 분기에 `created_by` 필터가 **다시 생기면 실패**한다.
   ⚠️ 단 **viewer(영업사원) 격리는 그대로여야 한다** — 그것까지 풀리면 보안 경계가 뚫린다.

③ **이름 정규화 규칙이 서버·화면에서 갈라지는 것**.
   검색은 화면(JS)과 서버(Python) 양쪽에서 비교한다. 한쪽만 고치면
   「화면에선 찾히는데 서버는 모른다」가 된다.

⚠️ 표준 라이브러리만 쓴다(배포 게이트에 fastapi·pydantic 이 없다).
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
FE = os.path.join(ROOT, "frontend", "js")

_pass = _fail = 0


def ok(name, cond, note=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}" + (f"  — {note}" if note else ""))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_js_comments(src):
    """주석을 **같은 길이의 공백**으로 바꾼다(줄바꿈은 남긴다 — 줄 번호가 안 밀린다).

    ⚠️ 왜 필요한가 — 첫 판에서 이 시험이 **내가 쓴 주석 속 `api.post('/products/track')`**
       를 진짜 호출로 읽고 실패했다. 설명을 적었다고 시험이 깨지면 아무도 설명을 안 적는다.
    ⚠️ 따옴표·백틱 안은 건드리지 않는다 — `https://…` 의 `//` 를 주석으로 오인하면
       문자열이 통째로 날아가 **반대 방향 오판**이 난다.
    """
    out = []
    i, n = 0, len(src)
    quote = None            # 현재 열려 있는 따옴표(' " `)
    while i < n:
        c = src[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:       # 이스케이프는 통째로 넘긴다
                out.append(src[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ==================================================================
# ① 화면에서 /products/track 를 부르는 자리는 전부 client_id 를 보낸다
# ==================================================================
def test_track_callers_send_client_id():
    callers = []
    for root, _dirs, files in os.walk(FE):
        for fn in files:
            if not fn.endswith((".jsx", ".js")):
                continue
            path = os.path.join(root, fn)
            src = strip_js_comments(read(path))     # 주석 속 예시에 속지 않는다
            if "products/track" not in src:
                continue
            callers.append((os.path.relpath(path, ROOT), src))

    ok("화면에서 /products/track 를 부르는 파일을 찾았다", len(callers) > 0,
       "한 곳도 못 찾았다 — 경로가 바뀌었는지 확인할 것")

    for rel, src in callers:
        # 그 호출이 들어 있는 구간만 본다(파일 전체에 client_id 가 있어도 통과시키지 않기 위해).
        for m in re.finditer(r"""(?:api\.post|await\s+api\.post)\s*\(\s*['"]/products/track['"]""", src):
            start = m.start()
            # 호출 시작부터 닫는 괄호까지를 괄호 깊이로 잘라 낸다.
            # ⚠️ `api.post(` 의 여는 괄호는 이미 지나쳤으므로 **깊이 1 에서 시작**한다.
            #    0 에서 시작하면 첫 인자 안의 `regUrl.trim()` 하나에 구간이 잘려
            #    뒤에 있는 client_id 를 못 보고 **멀쩡한 코드를 실패로 만든다**(첫 판에 겪었다).
            depth = 1
            end = min(len(src), start + 4000)
            for i in range(m.end(), min(len(src), start + 4000)):
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            call = src[start:end]
            line = src[:start].count("\n") + 1
            ok(f"{rel}:{line} 의 /products/track 호출이 client_id 를 보낸다",
               "client_id" in call,
               "업체 없이 보내면 서버가 400 으로 거절한다 — 버튼이 죽는다")


# ==================================================================
# ② registered-clients — manager 는 전체, viewer 는 본인 것만
# ==================================================================
def _func_src(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def test_registered_clients_scope():
    src = read(os.path.join(BACKEND, "client_dashboard.py"))
    fn = _func_src(src, "registered_clients")
    ok("registered_clients 를 찾았다", bool(fn))

    # viewer 격리는 살아 있어야 한다
    ok("viewer 분기가 본인 것만 보도록 남아 있다",
       "viewer" in fn and "created_by = ?" in fn,
       "영업사원 격리가 풀리면 보안 경계가 뚫린다")

    # viewer 분기 **밖**에 created_by 필터가 남아 있으면 안 된다
    #   (대표 확정 2026-09-14 「모두 보게 하자」 — manager 도 광고주 전체를 본다)
    viewer_q = re.findall(r"role\s*,'advertiser'\)='prospect'[^\"]*created_by = \?", fn)
    total_q = re.findall(r"created_by = \?", fn)
    ok("manager 분기에 created_by 필터가 없다",
       len(total_q) == len(viewer_q) == 1,
       f"created_by 조건 {len(total_q)}개 발견 — viewer 용 1개만 있어야 한다")

    ok("advertiser 전체를 주는 분기가 있다",
       "='advertiser' ORDER BY name ASC" in fn.replace("COALESCE(role,'advertiser')", "").replace(" ", " "),
       "광고주 전체 목록 질의를 못 찾았다")


# ==================================================================
# ③ 이름 정규화 — 서버(Python)와 화면(JS)이 같은 규칙이어야 한다
# ==================================================================
def _load_lookup_norm():
    src = read(os.path.join(BACKEND, "client_dashboard.py"))
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "lookup_norm":
            mod = ast.Module(body=[node], type_ignores=[])
            ns = {}
            exec(compile(mod, "<lookup_norm>", "exec"), ns)
            return ns["lookup_norm"]
    return None


def test_lookup_norm_behaviour():
    f = _load_lookup_norm()
    ok("서버에 lookup_norm 이 있다", f is not None)
    if not f:
        return
    cases = [
        ("메타 아이앤씨", "메타아이앤씨"),
        ("유성 프레시(본점)", "유성프레시본점"),
        ("A-B_C", "abc"),
        ("가 나  다", "가나다"),
        ("오'네일", "오네일"),
        ("", ""),
        (None, ""),
        ("카페·베이커리", "카페베이커리"),
        ("A&B+C", "abc"),
        ("한/일", "한일"),
    ]
    for raw, want in cases:
        ok(f"lookup_norm({raw!r}) == {want!r}", f(raw) == want, f"실제 {f(raw)!r}")

    # 정규화가 **원문을 바꾸지 않는다**는 것 — 비교용일 뿐
    ok("정규화는 비교용이다(원문 훼손 금지)", f("메타 아이앤씨") != "메타 아이앤씨")


def test_norm_rules_match_between_server_and_screen():
    py = read(os.path.join(BACKEND, "client_dashboard.py"))
    js = read(os.path.join(FE, "utils.js"))

    m_py = re.search(r'_re\.sub\(r"\[(.*?)\]"', py)
    m_js = re.search(r"replace\(/\[(.*?)\]/g", js)
    ok("서버 정규화 문자 집합을 찾았다", m_py is not None)
    ok("화면 정규화 문자 집합을 찾았다", m_js is not None)
    if not (m_py and m_js):
        return

    def charset(expr):
        # 이스케이프를 벗겨 문자 집합만 비교한다(표기 차이는 무시)
        return set(re.sub(r"\\(.)", r"\1", expr))

    a, b = charset(m_py.group(1)), charset(m_js.group(1))
    ok("서버와 화면이 **같은** 정규화 규칙을 쓴다", a == b,
       f"서버에만 {sorted(a - b)} · 화면에만 {sorted(b - a)}")


# ==================================================================
# ④ clients-lookup 이 「왜 안 나오는지」를 돌려준다
# ==================================================================
def test_lookup_explains_why():
    src = read(os.path.join(BACKEND, "client_dashboard.py"))
    fn = _func_src(src, "clients_lookup")
    ok("clients_lookup 을 찾았다", bool(fn))
    ok("내린 업체를 blocked 로 돌려준다", '"blocked"' in fn and "terminated" in fn,
       "0건과 「내린 업체라 안 나온다」를 화면이 못 가른다")
    ok("잘렸는지(truncated)를 돌려준다", '"truncated"' in fn)
    ok("data 에 role 이 실린다", '"role"' in fn)
    ok("기존 계약대로 data 는 그대로 배열이다", '"data"' in fn)
    ok("정규화 비교를 쓴다", "lookup_norm" in fn)


def test_lookup_matching_logic():
    """서버 매칭 규칙을 그대로 재현해 「공백이 달라도 찾힌다」를 실증한다."""
    f = _load_lookup_norm()
    if not f:
        return
    names = ["메타 아이앤씨", "유성프레시", "청귤농장(제주)", "가나다"]

    def hit(key, nm):
        nkey, lkey = f(key), key.lower()
        if not key:
            return True
        return (lkey in nm.lower()) or (bool(nkey) and nkey in f(nm))

    ok("「메타아이앤씨」로 「메타 아이앤씨」가 찾힌다", hit("메타아이앤씨", names[0]))
    ok("「메타 아이앤씨」로도 찾힌다(원문 그대로도 된다)", hit("메타 아이앤씨", names[0]))
    ok("「청귤농장 제주」로 「청귤농장(제주)」가 찾힌다", hit("청귤농장 제주", names[2]))
    ok("관계없는 검색어는 안 찾힌다", not hit("없는이름", names[0]))
    ok("빈 검색어는 전부 통과(목록 전체)", hit("", names[0]))


if __name__ == "__main__":
    print("=== 업체 피커·추적 등록 회귀 시험 (신고 #265 #266) ===")
    test_track_callers_send_client_id()
    test_registered_clients_scope()
    test_lookup_norm_behaviour()
    test_norm_rules_match_between_server_and_screen()
    test_lookup_explains_why()
    test_lookup_matching_logic()
    print(f"\n통과 {_pass} · 실패 {_fail}")
    sys.exit(1 if _fail else 0)
