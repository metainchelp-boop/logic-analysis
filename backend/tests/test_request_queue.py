"""요청 큐 회귀 — 배치가 자기 일을 큐에 되넣지 않고, 오래된 대기는 사라진다.

⚠️ 이 시험이 생긴 경위 (2026-09-11 실측)
   수집을 꺼 둔 날인데도 큐에 **하루 576건이 새로 들어왔다.** 시각을 보니 89%(513건)가
   08~09시 배치 창이었고 08:30~08:41 에 분당 15~16건 균일 — 사람이 아니라 배치다.
   8/28 에 되먹임을 막을 때 `enqueue_on_miss=False` 를 6곳에 걸었는데
   **`_get_product_info_impl` 의 1차 키워드 경로와 `search_products` 가 빠져 있었다**
   (같은 함수의 2차 스토어명 경로는 막혀 있었다).
   같은 날 pending 956건 중 **934건이 attempts=0** 이었다 — 확장이 꺼져 있으면
   아무도 attempts 를 올리지 않아 「5회 소진 후 7일」 정리가 영원히 안 걸린다.

⚠️ collector.py·naver_crawler.py 는 fastapi·bs4 를 끌어와 배포 게이트 환경에서 import 가
   안 된다. 그래서 **소스로 검사**한다(이 저장소의 기존 방식 — test_analysis_regression 참조).
   검사 대상이 「호출부가 플래그를 넘기는가」라서 소스 검사가 오히려 정확하다.

표준 라이브러리만 쓴다.
"""

import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _src(name):
    with io.open(os.path.join(_HERE, "..", name), encoding="utf-8") as f:
        return f.read()


def _calls_with_window(src, names, window=4):
    """호출 줄과 그 뒤 window 줄을 묶어 돌려준다 — 인자가 다음 줄로 넘어가는 경우 대비."""
    lines = src.splitlines()
    pat = re.compile(r"(?:%s)\(" % "|".join(names))
    out = []
    for i, l in enumerate(lines):
        if pat.search(l) and not l.lstrip().startswith(("def ", "#", "*")):
            out.append((i + 1, l.strip(), "\n".join(lines[i:i + window])))
    return out


# ⚠️ 2026-09-12 추가 — 배치가 **화면용 함수를 빌려 쓰는** 경로도 같은 목록에 넣는다.
#    PR #199 는 이 목록에 없던 `compute_advertiser_report` 때문에 절반만 막혔다.
_FETCHERS = ["search_naver_shopping_api", "search_products",
             "find_product_rank", "get_product_info",
             "compute_advertiser_report", "_shared_crawl"]


def test_batch_never_refills_the_queue():
    """⭐ 핵심 — 배치 모듈의 모든 수집 호출은 enqueue_on_miss=False 를 넘긴다.

    한 자리만 빠져도 08:30 배치가 큐를 매일 되채운다(9/11 실측: 하루 513건).
    """
    bad = []
    for f in ("scheduler.py", "auto_analysis.py"):
        for ln, line, win in _calls_with_window(_src(f), _FETCHERS):
            if "enqueue_on_miss=False" not in win:
                bad.append(f"{f}:{ln}  {line[:70]}")
    assert not bad, "배치가 큐에 되넣는 호출이 있다:\n  " + "\n  ".join(bad)


def test_flag_is_threaded_through_every_hop():
    """플래그가 체인 중간에서 끊기면 배치가 False 를 줘도 안쪽에서 큐에 들어간다."""
    nc = _src("naver_crawler.py")
    for sig in ("def search_products(", "def find_product_rank(",
                "def get_product_info(", "def _get_product_info_impl(",
                "def search_naver_shopping_api("):
        i = nc.find(sig)
        assert i >= 0, f"함수를 못 찾았다: {sig}"
        head = nc[i:i + 400].split(":\n", 1)[0]
        assert "enqueue_on_miss" in head, f"{sig} 가 플래그를 안 받는다 — 체인이 끊긴다"

    # 안쪽으로 그대로 넘기는지 (값을 True/False 로 굳혀 버리면 체인이 끊긴 것과 같다)
    for caller, callee in (("def search_products(", "search_naver_shopping_api("),
                           ("def find_product_rank(", "search_products("),
                           ("def get_product_info(", "_get_product_info_impl(")):
        i = nc.find(caller)
        body = nc[i:i + 3000]
        j = body.find(callee)
        assert j >= 0, f"{caller} 안에서 {callee} 를 못 찾았다"
        win = body[j:j + 300]
        assert "enqueue_on_miss=enqueue_on_miss" in win, \
            f"{caller} → {callee} 로 플래그를 그대로 넘기지 않는다"


def test_the_leaking_line_is_actually_fixed():
    """9/11 에 새던 그 자리 — 1차 키워드 경로. 2차와 같은 처리를 받아야 한다."""
    nc = _src("naver_crawler.py")
    i = nc.find("def _get_product_info_impl(")
    body = nc[i:i + 6000]
    calls = [w for _, _, w in _calls_with_window(body, ["search_naver_shopping_api"], window=5)]
    assert len(calls) >= 2, f"이 함수의 수집 호출이 2개 미만이다({len(calls)}) — 구조가 바뀌었다"
    for w in calls:
        assert "enqueue_on_miss" in w, "1차·2차 중 한쪽이 여전히 기본값(True)이다"


def test_screen_paths_keep_enqueueing():
    """무회귀 — 직원이 화면에서 조회한 것은 그대로 큐에 들어가야 한다.

    기본값이 True 여야 main.py 의 호출부를 한 줄도 안 고치고 종전 동작이 유지된다.
    """
    nc = _src("naver_crawler.py")
    for sig in ("def search_products(", "def find_product_rank(",
                "def get_product_info(", "def _get_product_info_impl("):
        i = nc.find(sig)
        head = nc[i:i + 400].split(":\n", 1)[0]
        assert "enqueue_on_miss: bool = True" in head, \
            f"{sig} 의 기본값이 True 가 아니다 — 화면 조회가 큐에 안 들어간다(무회귀 위반)"
    mn = _src("main.py")
    assert "search_naver_shopping_api(req.keyword" in mn, "화면 검색 경로가 사라졌다"


def test_stale_pending_is_pruned_even_while_collection_is_off():
    """⭐ 확장이 꺼져 있어도 큐가 무한히 자라지 않는다.

    종전 규칙은 `attempts >= 5` 를 요구했는데, 아무도 안 집으면 attempts 는 0에 머문다.
    """
    col = _src("collector.py")
    assert "STALE_PENDING_DAYS" in col, "나이 상한 상수가 없다"
    m = re.search(r"STALE_PENDING_DAYS\s*=\s*(\d+)", col)
    assert m and 1 <= int(m.group(1)) <= 30, f"나이 상한이 이상하다: {m and m.group(1)}"

    i = col.find("def prune_self_tail_requests(")
    assert i >= 0, "정리 함수가 없다"
    body = col[i:i + 4000]
    assert "STALE_PENDING_DAYS" in body, "정리 함수가 나이 상한을 안 쓴다"
    assert "attempts" not in body.split("STALE_PENDING_DAYS")[1][:400], \
        "나이 상한이 attempts 조건에 묶여 있다 — 확장이 꺼진 경우를 또 못 잡는다"
    assert "status='pending'" in body, "pending 만 대상으로 하는지 확인 불가"


def test_stale_prune_runs_without_the_extension():
    """정리가 확장 폴링(/requests)이 아니라 스케줄러에서 돌아야 한다 — 꺼져 있어도 돌게."""
    sch = _src("scheduler.py")
    assert "prune_self_tail_requests" in sch, "스케줄러가 큐 정리를 안 부른다"
    assert "stale" in sch, "정리 로그가 오래된 대기 건수를 말하지 않는다"


def test_live_db_is_never_a_prune_target():
    """안전 — 정리 대상은 collect_requests 행뿐이다(파일·다른 표를 지우지 않는다)."""
    col = _src("collector.py")
    i = col.find("def prune_self_tail_requests(")
    body = col[i:i + 4000]
    for danger in ("os.remove", "DROP TABLE", "DELETE FROM collected_serp",
                   "DELETE FROM clients", "DELETE FROM rankings"):
        assert danger not in body, f"정리 함수가 위험한 일을 한다: {danger}"


# ──────────────────────────────────────────────────────────────────────────
# 2026-09-12 — 배치가 화면용 함수(main.py)를 빌려 쓰는 경로
#
# ⚠️ 경위: PR #199 를 배포한 다음 날 아침에도 큐가 찼다(08:30~ 분당 ~12.5건, 그날 오전만
#    200건 넘게). 배포본에는 고침이 분명히 들어 있었다(서버 실측: 표지·정정 주석 확인).
#    범인은 `auto_analysis` 가 키워드마다 부르는 **`main.compute_advertiser_report`** 였다.
#    그 안에서 `get_product_info` · `search_products` · `_shared_crawl` 이 기본값(True)으로
#    돌아 키워드 1개당 큐 1건이 들어갔다.
#
# ⭐ 교훈: 「배치가 무엇을 부르는가」를 셀 때 **직접 호출만 세면 절반이다.**
#    배치가 화면 쪽 함수를 빌려 쓰면 그 안쪽은 화면 기본값으로 돈다.
#    아래 시험은 이름을 하나 더 적는 대신 **빌려 쓰는 관계 자체**를 검사한다 —
#    다음에 새 함수를 빌려 써도 먼저 깨진다.
# ──────────────────────────────────────────────────────────────────────────

_BATCH_MODULES = ("scheduler.py", "auto_analysis.py", "rank_record.py")


def _borrowed_from_main(src):
    """배치 모듈이 main 에서 끌어다 쓰는 이름들 (지연 임포트 포함)."""
    out = set()
    for m in re.finditer(r"from\s+main\s+import\s+([^\n(]+)", src):
        for name in m.group(1).split(","):
            name = name.strip().split(" as ")[0].strip()
            if name and not name.startswith("*"):
                out.add(name)
    return out


def test_every_borrowed_screen_function_is_called_with_the_flag_off():
    """⭐ 배치가 main 에서 빌려 쓰는 함수는 전부 enqueue_on_miss=False 로 불러야 한다.

    이름 목록을 늘리는 방식이 아니라 **빌려 쓰는 관계**를 보므로,
    다음에 새 함수를 빌려 써도 이 시험이 먼저 깨진다.
    """
    bad = []
    for f in _BATCH_MODULES:
        try:
            src = _src(f)
        except IOError:
            continue
        borrowed = _borrowed_from_main(src)
        if not borrowed:
            continue
        for ln, line, win in _calls_with_window(src, [re.escape(n) for n in borrowed]):
            if "enqueue_on_miss=False" not in win:
                bad.append("%s:%d  %s" % (f, ln, line[:70]))
    assert not bad, ("배치가 화면용 함수를 기본값(True)으로 부른다 — 큐가 매일 다시 찬다:\n  "
                     + "\n  ".join(bad))


def test_the_borrowed_function_threads_the_flag_inward():
    """빌려 쓰는 함수가 플래그를 받아 **안쪽까지** 넘기지 않으면 False 를 줘도 소용없다."""
    mn = _src("main.py")
    for sig in ("def compute_advertiser_report(", "def _shared_crawl("):
        i = mn.find(sig)
        assert i >= 0, "함수를 못 찾았다: %s" % sig
        head = mn[i:i + 400].split(":\n", 1)[0]
        assert "enqueue_on_miss: bool = True" in head, \
            "%s 가 플래그를 기본 True 로 받지 않는다(화면 무회귀 + 배치 차단 둘 다 필요)" % sig

    i = mn.find("def compute_advertiser_report(")
    body = mn[i:i + 6000]
    inner = [w for _, _, w in _calls_with_window(
        body, ["get_product_info", "_sp", "_shared_crawl", "find_product_rank"], window=6)]
    assert inner, "compute_advertiser_report 안에서 수집 호출을 못 찾았다 — 구조가 바뀌었다"
    for w in inner:
        assert "enqueue_on_miss=enqueue_on_miss" in w, \
            "compute_advertiser_report 안에 플래그를 안 넘기는 수집 호출이 남아 있다"

    i = mn.find("def _shared_crawl(")
    body = mn[i:i + 2000]
    j = body.find("_sp(keyword")
    assert j >= 0, "_shared_crawl 안에서 실제 크롤 호출을 못 찾았다"
    assert "enqueue_on_miss=enqueue_on_miss" in body[j:j + 300], \
        "_shared_crawl 이 크롤 호출에 플래그를 안 넘긴다"


def test_screen_still_enqueues_through_the_borrowed_function():
    """무회귀 — 직원이 화면에서 부르는 자리는 플래그를 안 준다(= 기본 True 로 큐에 들어간다)."""
    mn = _src("main.py")
    i = mn.find("def check_rank(")
    assert i >= 0, "화면 순위 조회 경로가 사라졌다"
    body = mn[i:i + 1500]
    assert "_shared_crawl(req.keyword" in body, "화면 경로가 공용 크롤을 안 쓴다"
    assert "enqueue_on_miss=False" not in body, \
        "화면 순위 조회가 큐에 안 들어가게 바뀌었다 — 무회귀 위반"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
