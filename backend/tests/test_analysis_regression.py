"""
분석 실행 신뢰도 회귀 테스트 (네트워크 없이 결정적으로 실행).

2026-06 신뢰도 하드닝에서 수정한 결함이 재발하지 않도록 잠근다.
외부 네트워크는 차단하고 순수 파싱/계산 로직만 검증한다.

실행:  python tests/test_analysis_regression.py   (또는 pytest tests/)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 외부 네트워크 차단 — 테스트는 결정적이어야 하므로 실제 크롤/API 호출을 막는다.
import requests as _rq  # noqa: E402


def _no_net(*a, **k):
    raise RuntimeError("network disabled in tests")


_rq.get = _no_net
_rq.post = _no_net

import naver_crawler as nc  # noqa: E402

_URL = "https://shopping.naver.com/window-products/nature/12345"


def test_price_meta_recovered():
    """#1 가격 유실: 합성 HTML의 api-price 메타에서 판매가를 회수해야 한다."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta name="api-review-count" content="7">'
        '<meta name="api-review-score" content="5.0">'
        '<meta name="api-wish-count" content="10">'
        '<meta name="api-price" content="13000">'
        '</head><body><div class="product-detail"><h1>테스트상품</h1>'
        '<div class="detail_content" id="product_detail">상세 설명 텍스트</div></div></body></html>'
    )
    rd = (nc.analyze_detail_page(html, _URL) or {}).get("reviewData") or {}
    assert rd.get("price") == 13000, f"price expected 13000, got {rd.get('price')!r}"


def test_zero_review_not_inflated():
    """#3 0리뷰 오인: 진짜 0리뷰가 프로모 문구 숫자로 부풀려지지 않아야 한다."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta name="api-review-count" content="0">'
        '<meta name="api-wish-count" content="5">'
        '</head><body>리뷰 작성 시 1,000원 적립 · 리뷰 1000 이벤트'
        '<div class="product-detail"><h1>x</h1></div></body></html>'
    )
    rd = (nc.analyze_detail_page(html, _URL) or {}).get("reviewData") or {}
    assert rd.get("reviewCount") in (0, None), f"reviewCount expected 0/None, got {rd.get('reviewCount')!r}"


def test_price_meta_non_numeric_safe():
    """#1 방어: api-price가 비정상 값이어도 예외 없이 None/0 처리되어야 한다."""
    for bad in ("abc", "", "inf", "1,2,3"):
        html = (
            '<!DOCTYPE html><html><head>'
            '<meta name="api-review-count" content="3">'
            f'<meta name="api-price" content="{bad}">'
            '</head><body><div class="product-detail"><h1>x</h1></div></body></html>'
        )
        rd = (nc.analyze_detail_page(html, _URL) or {}).get("reviewData") or {}
        assert rd.get("price") in (None, 0), f"bad price {bad!r} -> {rd.get('price')!r}"


def test_growth_month_keys_match_calendar():
    """datalab #3: 캘린더 월 인덱스로 만든 %Y-%m 키가 실제 캘린더 월과 일치해야 한다."""
    from datetime import datetime

    for now in (datetime(2026, 7, 1), datetime(2026, 1, 15), datetime(2026, 12, 31), datetime(2027, 3, 3)):
        base_idx = now.year * 12 + (now.month - 1)
        for i in range(24):
            m_idx = base_idx - i
            y, mo = divmod(m_idx, 12)
            key = f"{y:04d}-{mo + 1:02d}"
            yy, mm = now.year, now.month - i
            while mm <= 0:
                mm += 12
                yy -= 1
            expect = f"{yy:04d}-{mm:02d}"
            assert key == expect, f"{now} i={i}: {key} != {expect}"
            # 전년 동월
            assert f"{y - 1:04d}-{mo + 1:02d}" == f"{yy - 1:04d}-{mm:02d}"


def test_anomaly_guard_absurd_review_count():
    """이상탐지: 비현실적 리뷰수(>2,000,000)는 미확인(None) 처리."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta name="api-review-count" content="9999999">'
        '</head><body><div class="product-detail"><h1>x</h1></div></body></html>'
    )
    rd = (nc.analyze_detail_page(html, _URL) or {}).get("reviewData") or {}
    assert rd.get("reviewCount") is None, f"absurd review -> {rd.get('reviewCount')!r}"


def test_anomaly_guard_price_out_of_range():
    """이상탐지: 상식 범위 밖 판매가(100원 미만/1억 초과)는 미확인 처리."""
    for bad in ("50", "999999999"):
        html = (
            '<!DOCTYPE html><html><head>'
            '<meta name="api-review-count" content="3">'
            f'<meta name="api-price" content="{bad}">'
            '</head><body><div class="product-detail"><h1>x</h1></div></body></html>'
        )
        rd = (nc.analyze_detail_page(html, _URL) or {}).get("reviewData") or {}
        assert rd.get("price") in (None, 0), f"out-of-range price {bad} -> {rd.get('price')!r}"


def test_data_quality_status_tags():
    """지능층: data_quality가 각 수치에 실측/미확인 상태를 붙인다."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta name="api-review-count" content="7">'
        '<meta name="api-price" content="13000">'
        '</head><body><div class="product-detail"><h1>x</h1></div></body></html>'
    )
    rd = (nc.analyze_detail_page(html, _URL) or {}).get("reviewData") or {}
    q = rd.get("data_quality") or {}
    assert q.get("review_count", {}).get("status") == "measured", q.get("review_count")
    assert q.get("price", {}).get("status") == "measured", q.get("price")
    assert q.get("rating", {}).get("status") == "unavailable", q.get("rating")  # 평점 메타/리뷰 없음
    assert q.get("review_count", {}).get("confidence") == "medium"


def test_data_quality_cross_check_unit():
    """지능층: cross_check 상태 전이(교차확인/불일치/한쪽/없음)."""
    import data_quality as dq
    assert dq.cross_check(4.5, 4.6, tol=0.5)[1] == "cross_verified"
    assert dq.cross_check(4.5, 3.0, tol=0.5)[1] == "measured"
    assert dq.cross_check(4.5, None)[1] == "measured"
    assert dq.cross_check(None, None)[1] == "unavailable"
    assert dq.confidence("cross_verified") == "high"
    assert dq.label("estimated") == "추정"


def test_match_item_rejects_wrong_store_product():
    """오매칭 회귀 가드(#83): productId를 뽑은 URL에서 같은 스토어의
    '다른 상품(대표상품)'을 스토어명만으로 매칭하지 않는다.
    (지정 상품 대신 스토어의 리뷰 많은 대표 상품으로 바뀌던 버그 재발 방지.)"""
    url = "https://smartstore.naver.com/gyuloreum/products/123"  # 지정 상품 productId=123
    wrong = {"productId": "777",  # 같은 스토어의 '다른' 상품(대표)
             "link": "https://smartstore.naver.com/gyuloreum/products/777",
             "title": "대표상품 리뷰많음", "mallName": "gyuloreum", "image": "", "lprice": "9900"}
    _orig = nc.search_naver_shopping_api
    nc.search_naver_shopping_api = lambda *a, **k: {"items": [wrong]}
    try:
        rd = nc._get_product_info_impl(url, keyword="한라봉")
    finally:
        nc.search_naver_shopping_api = _orig
    assert rd.get("product_name") != "대표상품 리뷰많음", \
        f"오매칭 재발! 같은 스토어 다른 상품을 잡음: {rd.get('product_name')!r}"


def test_keyword_volume_contract_fields():
    """계약 가드: get_keyword_volume이 제안서·ERP가 소비하는 필드
    (monthlyPcQcCnt/monthlyMobileQcCnt/compIdx)를 항상 내보낸다.
    이 필드명·구조가 바뀌면 제안서 '월 검색량'이 깨진다(반복 신고 부류)."""
    class _Resp:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"keywordList": [{
                "relKeyword": "한라봉", "monthlyPcQcCnt": 12000, "monthlyMobileQcCnt": 30000,
                "monthlyAvePcClkCnt": 10, "monthlyAveMobileClkCnt": 20, "plAvgDepth": 15, "compIdx": "높음",
            }]}
    _keys = (nc.SEARCHAD_API_KEY, nc.SEARCHAD_SECRET_KEY, nc.SEARCHAD_CUSTOMER_ID)
    _get = nc.requests.get
    nc.SEARCHAD_API_KEY, nc.SEARCHAD_SECRET_KEY, nc.SEARCHAD_CUSTOMER_ID = "k", "s", "c"
    nc.requests.get = lambda *a, **k: _Resp()
    try:
        out = nc.get_keyword_volume(["한라봉"])
    finally:
        nc.SEARCHAD_API_KEY, nc.SEARCHAD_SECRET_KEY, nc.SEARCHAD_CUSTOMER_ID = _keys
        nc.requests.get = _get
    assert out and isinstance(out, list), f"빈 결과: {out!r}"
    r0 = out[0]
    for f in ("monthlyPcQcCnt", "monthlyMobileQcCnt", "compIdx"):
        assert f in r0, f"계약 필드 누락: {f} — 제안서 '월 검색량' 깨짐. keys={list(r0.keys())}"
    assert r0["monthlyPcQcCnt"] == 12000 and r0["monthlyMobileQcCnt"] == 30000, \
        f"검색량 파싱 오류: {r0!r}"


# ==================== 순위를 한 번만 재서 나눠 적기 (2026-08-27) ====================
# 대표 지시 「순위 추적 1번만 진행하고 필요한 곳에 보내주기」.
# 잘못되면 남의 업체 순위가 섞이거나, 업체 대표 상품 기준 순위가 덮여 화면이 바뀐다.
from rank_link import share_targets  # noqa: E402


def test_share_이어진_업체에_나눠_적는다():
    assert share_targets({10: [100, 200]}, {}, 10, "고구마") == [100, 200]


def test_share_안_이어진_상품은_아무데도_안_적는다():
    assert share_targets({10: [100]}, {}, 99, "고구마") == []


def test_share_그_업체가_이미_재는_키워드는_건드리지_않는다():
    # 업체 100 은 「고구마」를 자기 대표 상품으로 이미 재고 있다 → 덮어쓰지 않는다(무회귀).
    got = share_targets({10: [100, 200]}, {100: ["고구마", "밤고구마"]}, 10, "고구마")
    assert got == [200], f"대표 상품 기준 순위를 덮어쓰려 한다: {got!r}"


def test_share_다른_키워드는_그대로_나눠_적는다():
    assert share_targets({10: [100]}, {100: ["고구마"]}, 10, "호박고구마") == [100]


def test_share_자격_없는_업체는_애초에_목록에_없다():
    # 계약이 끝난 업체는 배치가 link_map 을 만들 때 이미 걸러 낸다.
    assert share_targets({10: []}, {}, 10, "고구마") == []


def test_share_키워드_목록이_없어도_터지지_않는다():
    assert share_targets({10: [100]}, {100: None}, 10, "고구마") == [100]


# ==================== 여러 대로 나눠 돌리기 (2026-08-27) ====================
# 대표 지시 「1번 기기가 앞쪽, 2번 기기가 뒤쪽 — 겹치지 않게」.
# 잘못되면 같은 키워드를 두 대가 같이 하거나(낭비), 아무도 안 한다(누락).
# ⚠️ split_rule 은 표준 라이브러리만 쓴다 — collector.py 는 fastapi 를 임포트해서
#    이 게이트가 도는 환경에서는 불러올 수가 없다(그래서 규칙을 따로 뒀다).
from split_rule import split_ok, worker_of, normalize  # noqa: E402

_KWS = [f"키워드{i}" for i in range(500)] + ["고구마", "한우", "제주감귤", "오메기떡"]


def test_split_두대가_겹치지도_빠지지도_않는다():
    a = [k for k in _KWS if split_ok(k, 0, 2)]
    b = [k for k in _KWS if split_ok(k, 1, 2)]
    assert not (set(a) & set(b)), "두 대가 같은 키워드를 맡는다(중복 수집)"
    assert set(a) | set(b) == set(_KWS), "아무도 안 맡는 키워드가 있다(누락)"


def test_split_세대도_마찬가지():
    gs = [set(k for k in _KWS if split_ok(k, i, 3)) for i in range(3)]
    assert sum(len(g) for g in gs) == len(_KWS)
    assert set().union(*gs) == set(_KWS)
    assert not (gs[0] & gs[1]) and not (gs[1] & gs[2]) and not (gs[0] & gs[2])


def test_split_한대면_전량_종전그대로():
    # ⚠️ 지금 도는 기계가 아무것도 안 바뀌어야 한다.
    assert all(split_ok(k, 0, 1) for k in _KWS)
    assert all(split_ok(k, 0, 0) for k in _KWS)


def test_split_치우침이_심하지_않다():
    a = sum(1 for k in _KWS if split_ok(k, 0, 2))
    b = len(_KWS) - a
    assert abs(a - b) <= len(_KWS) * 0.1, f"한쪽에 몰린다: {a} vs {b}"


def test_split_같은_키워드는_항상_같은_기계():
    # 재실행할 때마다 담당이 바뀌면 그날 수집이 통째로 어긋난다.
    assert all(worker_of(k, 2) == worker_of(k, 2) for k in _KWS)
    assert worker_of("고구마", 2) == worker_of("고구마", 2)


def test_split_잘못된_번호는_안전하게_접힌다():
    assert normalize(5, 2) == (0, 2)      # 범위 밖 번호 → 1번으로
    assert normalize(-1, 2) == (0, 2)
    assert normalize(0, 0) == (0, 1)      # 대수 0 → 1대
    assert normalize(1, 3) == (1, 3)      # 정상값은 그대로


# ─────────────────────────────────────────────────────────────────────
# 순위 추적 자격 판정 (tracking_eligibility)
#
# ⚠️ 왜 검사하는가 — 2026-08-28 실측에서 이 판정이 **세 곳에 각각 다르게** 박혀
#    있었고, 08:00 기록 배치만 조건이 2개 모자라 **계약이 끝난 업체 65곳의 순위가
#    매일 계속 쌓이고 있었다**. 한 곳으로 모은 뒤로는 여기서 고정한다.
from tracking_eligibility import (              # noqa: E402
    eligible_client_ids, eligible_tracked_product_ids, ensure_disabled_column)


def _elig_db():
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE clients(id INTEGER PRIMARY KEY, status TEXT, role TEXT,
            vertical TEXT, auto_analysis INT, track_enabled INT, track_until TEXT);
        CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, created_at TEXT);
        CREATE TABLE rank_link(tracked_product_id INT, client_id INT);
    """)
    rows = [
        (1, "active", "advertiser", "store", 1, 1, ""),            # 정상
        (2, "active", "advertiser", "store", 1, 1, "2020-01-01"),  # 추적기간 지남
        (3, "active", "advertiser", "store", 0, 1, ""),            # 자동분석 OFF(계약만료·환불·홀딩)
        (4, "active", "advertiser", "store", 1, 0, ""),            # 추적 OFF(수동)
        (5, "active", "prospect",   "store", 1, 1, ""),            # 영업 대상
        (6, "active", "advertiser", "place", 1, 1, ""),            # 플레이스 축
        (7, "inactive", "advertiser", "store", 1, 1, ""),          # 비활성
    ]
    c.executemany("INSERT INTO clients VALUES(?,?,?,?,?,?,?)", rows)
    ensure_disabled_column(c)
    return c


def test_자격_계약_끝난_업체는_빠진다():
    c = _elig_db()
    assert eligible_client_ids(c) == [1], "자격 업체는 1번뿐이어야 한다"


def test_자격_추적기간_빈값은_통과한다():
    # track_until 이 비어 있으면 '기간 제한 없음' — 이걸 만료로 읽으면 전 업체가 멈춘다.
    c = _elig_db()
    c.execute("UPDATE clients SET track_until=NULL WHERE id=1")
    assert 1 in eligible_client_ids(c)


def test_추적상품_자격없는_업체_것만_빠진다():
    c = _elig_db()
    for pid in (10, 11, 12):
        c.execute("INSERT INTO tracked_products(id, created_at) VALUES(?, '2020-01-01')", (pid,))
    c.execute("INSERT INTO rank_link VALUES(10, 1)")   # 자격 업체 것
    c.execute("INSERT INTO rank_link VALUES(11, 2)")   # 계약 끝난 업체 것
    got = eligible_tracked_product_ids(c)              # 12 = 아무데도 안 이어짐
    assert got == {10, 12}, got


def test_추적상품_주인없어_내린것은_빠진다():
    # 01:20 정리 잡이 붙인 표시. 되돌리려면 이 칸만 비우면 된다.
    c = _elig_db()
    c.execute("INSERT INTO tracked_products(id, created_at) VALUES(12, '2020-01-01')")
    assert eligible_tracked_product_ids(c) == {12}
    c.execute("UPDATE tracked_products SET disabled_at='2026-08-28' WHERE id=12")
    assert eligible_tracked_product_ids(c) == set()


def test_추적상품_판정_실패하면_전부_잰다():
    # 조회 하나가 실패했다고 순위 추적이 통째로 멈추면 안 된다 → None(=필터 안 함).
    import sqlite3
    c = sqlite3.connect(":memory:")   # 표가 아예 없다
    assert eligible_tracked_product_ids(c) is None


def test_자격_컬럼_보장은_두번_불러도_안전():
    c = _elig_db()
    ensure_disabled_column(c)         # 이미 있는 상태에서 또 불러도 터지지 않는다
    ensure_disabled_column(c)
    assert eligible_client_ids(c) == [1]


# ─────────────────────────────────────────────────────────────────────
# 추적 상품 등록 — 업체는 필수 (2026-08-28 대표 확정)
#
# ⚠️ 왜 검사하는가 — 종전엔 업체가 선택값이었고 **화면에 칸조차 없어서**, 등록하는 순간부터
#    주인이 없는 상품이 만들어졌다. 그렇게 41개가 쌓였고, 주인을 모르면 그 업체 계약이
#    끝나도 추적을 멈출 근거가 없어 계속 수집된다.
#    화면이 1차로 막지만, 옛 화면이 브라우저에 캐시로 남아 있을 수 있어 서버가 최종 방어선이다.
#    ⚠️ main.py 는 fastapi 를 import 하므로 게이트에서 못 읽는다 — 소스 문자열로 검사한다.

def _main_src():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "main.py"), encoding="utf-8") as f:
        return f.read()


def test_등록에_업체가_없으면_거절한다():
    src = _main_src()
    i = src.find("def track_product(")
    assert i > 0, "track_product 를 찾지 못했다"
    body = src[i:i + 2000]
    assert "if not req.client_id:" in body, "업체 필수 가드가 없다 — 주인 없는 상품이 다시 생긴다"
    assert "status_code=400" in body, "거절은 400 이어야 한다"


def test_거절_문구가_할_일을_알려준다():
    # 「등록 실패」만 뜨면 사람은 무엇을 해야 할지 모른다 — 새로고침을 안내해야 한다.
    src = _main_src()
    i = src.find("def track_product(")
    body = src[i:i + 2000]
    assert "새로고침" in body, "거절 문구가 다음 행동을 안내하지 않는다"


def test_등록_요청에_업체_칸이_있다():
    src = _main_src()
    i = src.find("class ProductAddRequest")
    assert i > 0
    assert "client_id" in src[i:i + 800], "요청 모델에 client_id 가 없다"


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    _failed = 0
    for _fn in _tests:
        try:
            _fn()
            print(f"PASS  {_fn.__name__}")
        except Exception as _e:
            _failed += 1
            print(f"FAIL  {_fn.__name__}: {_e}")
    print(f"\n{len(_tests) - _failed}/{len(_tests)} passed")
    sys.exit(1 if _failed else 0)
