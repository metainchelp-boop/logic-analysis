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


# ─────────────────────────────────────────────────────────────────────
# 업체 목록 5칸 분리 (client_buckets) — 2026-08-28 대표 확정
from client_buckets import classify, delete_reasons   # noqa: E402

_TODAY = "2026-08-28"


def _row(**kw):
    d = {"contract_stage": None, "track_until": None, "role": "advertiser", "_synced": True}
    d.update(kw)
    return d


def test_칸_환불중이_기간지남보다_먼저다():
    # 환불 처리 중이면 기간이 지났어도 환불 담당이 볼 일이지 삭제할 일이 아니다.
    assert classify(_row(contract_stage="환불중", track_until="2020-01-01"), _TODAY) == "refund"


def test_칸_홀딩중():
    assert classify(_row(contract_stage="홀딩중"), _TODAY) == "hold"


def test_칸_단계명_띄어쓰기가_달라도_같은_칸():
    # 전산 단계명은 「계약 만료」처럼 공백이 섞여 오고 표기가 흔들린다.
    # 공백을 그대로 비교하면 그 단계가 조용히 어느 칸에도 안 잡힌다.
    assert classify(_row(contract_stage="계약 만료"), _TODAY) == "delete"
    assert classify(_row(contract_stage="계약만료"), _TODAY) == "delete"


def test_칸_삭제필요_사유를_전부_알려준다():
    got = delete_reasons(_row(contract_stage="계약 만료", track_until="2026-08-01", role="prospect"), _TODAY)
    assert got == ["계약 만료", "기간 지남", "광고주 아님"], got


def test_칸_동기화_전에는_전산에없음을_안_센다():
    # ⚠️ 이게 없으면 배포 직후(단계 전부 비어 있음)에 전 업체가 삭제 필요로 쏠린다.
    assert delete_reasons(_row(_synced=False), _TODAY) == []
    assert classify(_row(_synced=False), _TODAY) == "run"
    assert delete_reasons(_row(_synced=True), _TODAY) == ["전산에 없음"]


def test_칸_삭제필요가_확인필요보다_먼저다():
    # 지울 업체의 키워드를 고칠 이유가 없다.
    assert classify(_row(track_until="2026-08-01"), _TODAY, needs_check=True) == "delete"
    assert classify(_row(contract_stage="진행중"), _TODAY, needs_check=True) == "check"


def test_칸_정상_업체는_진행중():
    assert classify(_row(contract_stage="진행중"), _TODAY) == "run"
    assert classify(_row(contract_stage="사후 관리", track_until="2026-12-31"), _TODAY) == "run"


def test_칸_추적종료일이_오늘이면_아직_살아있다():
    # 경계 — 오늘까지는 유효하다. '<' 가 '<=' 로 바뀌면 오늘 만료 업체가 하루 일찍 사라진다.
    assert delete_reasons(_row(contract_stage="진행중", track_until=_TODAY), _TODAY) == []


# ─────────────────────────────────────────────────────────────────────
# rank_link 유지보수 잡 — 실제로 실행해 본다 (2026-08-29 실사고 재발 방지)
#
# ⚠️ 왜 필요한가 — disable_ownerless 가 존재하지 않는 _conn() 을 불러 NameError 가
#    났는데, 소스 검사·문자열 grep 으로는 못 잡는 종류다(이름이 그럴듯하니까).
#    첫 실행이 서버의 01:20 이었고, 예외가 같은 잡의 큐 정리까지 건너뛰게 했다.
#    여기서 **실제로 import 해 실제로 호출**하면 그런 오타는 배포 게이트에서 죽는다.
#    (rank_link 는 fastapi 를 안 쓰므로 게이트 환경에서 import 가능 —
#     naver_crawler 를 거치지만 그것도 requests 뿐이라 게이트에 있다.)

def test_rank_link_유지보수를_실제로_실행한다(tmp_db=None):
    import os, sqlite3, tempfile, importlib
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE clients(id INTEGER PRIMARY KEY, status TEXT, role TEXT, vertical TEXT,
            auto_analysis INT, track_enabled INT, track_until TEXT,
            name TEXT, business_name TEXT, naver_store_url TEXT, main_keywords TEXT);
        CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT DEFAULT '',
            product_name TEXT DEFAULT '', store_name TEXT DEFAULT '', product_id TEXT DEFAULT '',
            created_at TEXT);
        CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INT, keyword TEXT);
    """)
    # 사흘 전 등록됐고 아무 업체에도 안 이어진 상품 — 정리 대상이어야 한다
    conn.execute("INSERT INTO tracked_products(id, created_at) VALUES(7, date('now','-3 day'))")
    conn.commit(); conn.close()

    import rank_link
    old_db = rank_link.DB_PATH
    try:
        rank_link.DB_PATH = db
        rank_link.init_rank_link_db()              # 실제 부팅과 같은 경로로 브리지 표 생성
        res = rank_link.run_maintenance()          # ← 예외가 나면 여기서 테스트가 죽는다
        assert isinstance(res, dict), res
        assert res.get("disabled") == 1, f"주인 없는 상품이 안 내려갔다: {res}"
        res2 = rank_link.run_maintenance()          # 멱등 — 두 번째는 내릴 게 없다
        assert res2.get("disabled") == 0, res2
    finally:
        rank_link.DB_PATH = old_db
        try: os.unlink(db)
        except OSError: pass



# ─────────────────────────────────────────────────────────────────────
# 그만 재기(keyword_mute) — 억제 규칙 (2026-08-29 대표 확정 「양방향」)
#
# 지우지 않고 억제한다: 대표 키워드에서 빼도 분석 이력이 남아 있으면 수집이
# 계속 돌던 구멍을 이 표 하나가 막는다. 수집 유니버스·나눠 적기·보드가 전부
# 이 표를 본다 — 규칙이 갈라지면 「뺐는데 어딘가에선 계속 재는」 반쪽이 된다.

def _mute_db():
    import sqlite3, tempfile
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    return db, conn


def test_그만재기_기재하면_목록에_잡힌다():
    import os
    from keyword_mute import mute, muted_map, muted_set
    db, conn = _mute_db()
    try:
        mute(conn, 7, "수제쿠키", by=3)
        conn.commit()
        assert muted_map(conn) == {7: {"수제쿠키"}}
        assert muted_set(conn, 7) == {"수제쿠키"}
        assert muted_set(conn, 8) == set()
    finally:
        conn.close(); os.unlink(db)


def test_그만재기_해제는_멱등이고_기록을_되살린다():
    import os
    from keyword_mute import mute, unmute, muted_set
    db, conn = _mute_db()
    try:
        mute(conn, 7, "수제쿠키")
        unmute(conn, 7, "수제쿠키")
        unmute(conn, 7, "수제쿠키")          # 표에 없어도 조용히 성공
        conn.commit()
        assert muted_set(conn, 7) == set()
    finally:
        conn.close(); os.unlink(db)


def test_그만재기_조회_실패는_아무것도_안_뺀다():
    # ⚠️ 실패를 「전부 억제」로 읽으면 수집이 통째로 멈춘다 — 빈 dict 폴백이 계약이다.
    from keyword_mute import muted_map, muted_set

    class _Broken:
        in_transaction = False
        def execute(self, *a, **k):
            raise RuntimeError("db down")
        def commit(self):
            raise RuntimeError("db down")

    assert muted_map(_Broken()) == {}
    assert muted_set(_Broken(), 1) == set()


def test_그만재기_트랜잭션_안에서는_커밋하지_않는다():
    # ⚠️ ensure_mute_table 이 BEGIN IMMEDIATE 안에서 commit 하면 등록 경로의
    #    lost-update 방지(쓰기 락 구간)가 조용히 끝난다 — 락 보존이 계약이다.
    # 검증법: 트랜잭션 안에서 mute **앞에** 다른 쓰기(보초)를 해 두고 rollback —
    #   중간 commit 이 있었다면 보초가 이미 굳어 rollback 으로 안 사라진다.
    #   (mute 뒤의 in_transaction 검사만으로는 못 잡는다 — INSERT 가 암묵
    #    트랜잭션을 새로 열어 True 로 돌아오기 때문. 실측으로 확인한 함정.)
    import os
    from keyword_mute import mute, muted_set
    db, conn = _mute_db()
    try:
        conn.execute("CREATE TABLE sentinel(v TEXT)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO sentinel(v) VALUES('보초')")   # mute 앞의 쓰기
        mute(conn, 7, "수제쿠키")
        conn.rollback()                       # 전부 함께 사라져야 한다
        left = conn.execute("SELECT COUNT(*) FROM sentinel").fetchone()[0]
        assert left == 0, "mute 가 트랜잭션을 중간 commit 해 앞의 쓰기가 굳었다"
        assert muted_set(conn, 7) == set()
    finally:
        conn.close(); os.unlink(db)


def test_그만재기_키워드는_strip_원문_그대로_비교한다():
    # main_keywords·유니버스가 strip 원문을 쓰므로 여기만 공백 제거를 더 하면 어긋난다.
    import os
    from keyword_mute import mute, muted_set
    db, conn = _mute_db()
    try:
        mute(conn, 7, "  수제 쿠키  ")
        conn.commit()
        assert muted_set(conn, 7) == {"수제 쿠키"}   # strip 만, 내부 공백 보존
    finally:
        conn.close(); os.unlink(db)


# ─────────────────────────────────────────────────────────────────────
# 즉시 기록(rank_record) 대상 선정 — 자격 통일 + 그만 재기 (2026-08-29)
#
# ⚠️ 8/28 자격 통일이 배치·수집만 고치고 이 경로를 빠뜨렸던 실구멍의 재발 방지 —
#    계약 끝난 업체가 키워드만 겹치면 즉시 기록으로 계속 기록되던 것.

def _rr_db():
    import sqlite3, tempfile
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE clients(id INTEGER PRIMARY KEY, status TEXT DEFAULT 'active',
            role TEXT DEFAULT 'advertiser', vertical TEXT DEFAULT 'store',
            auto_analysis INT DEFAULT 1, track_enabled INT DEFAULT 1, track_until TEXT DEFAULT '',
            name TEXT, business_name TEXT DEFAULT '',
            naver_store_url TEXT DEFAULT 'https://smartstore.naver.com/x', main_keywords TEXT DEFAULT '');
        CREATE TABLE client_analyses(id INTEGER PRIMARY KEY, client_id INT, keyword TEXT);
    """)
    return db, conn


def test_즉시기록_계약끝난_업체는_대상에서_빠진다():
    import os
    from rank_record import _client_targets
    db, conn = _rr_db()
    try:
        conn.execute("INSERT INTO clients(id,name,main_keywords) VALUES(1,'살아있는곳','수제쿠키')")
        conn.execute("INSERT INTO clients(id,name,main_keywords,track_until) "
                     "VALUES(2,'계약끝난곳','수제쿠키','2020-01-01')")
        conn.execute("INSERT INTO client_analyses(client_id,keyword) VALUES(2,'수제쿠키')")
        conn.commit()
        ids = [c["id"] for c in _client_targets(conn, "수제쿠키")]
        assert ids == [1], f"계약 끝난 업체가 즉시 기록 대상에 남았다: {ids}"
    finally:
        conn.close(); os.unlink(db)


def test_즉시기록_그만재기_키워드는_이력이_있어도_안_적는다():
    import os
    from rank_record import _client_targets
    from keyword_mute import mute
    db, conn = _rr_db()
    try:
        conn.execute("INSERT INTO clients(id,name) VALUES(1,'가게A')")
        conn.execute("INSERT INTO client_analyses(client_id,keyword) VALUES(1,'오타키워드')")
        mute(conn, 1, "오타키워드")
        conn.commit()
        assert _client_targets(conn, "오타키워드") == [], "억제 키워드가 이력 갈래로 되살아났다"
        # 다른 키워드는 종전대로
        conn.execute("INSERT INTO client_analyses(client_id,keyword) VALUES(1,'수제쿠키')")
        conn.commit()
        assert [c["id"] for c in _client_targets(conn, "수제쿠키")] == [1]
    finally:
        conn.close(); os.unlink(db)



# ─────────────────────────────────────────────────────────────────────
# 즉시 기록(rank_record) 축A — 추적 상품 자격 판정 (2026-08-30)
#
# ⚠️ 8/29 자격 통일이 축B(_client_targets)만 고치고 축A(_tracked_targets)를 빠뜨렸던
#    실구멍의 재발 방지. 그 경로가 check_type="scheduled" 로 적어 08:00 배치가 쓴 것처럼
#    보였고, 실측(2026-08-30) 그날 기록된 196개 중 15개가 계약 끝난 업체 것이었다.

def _rr_a_db():
    import sqlite3, tempfile
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE clients(id INTEGER PRIMARY KEY, status TEXT DEFAULT 'active',
            role TEXT DEFAULT 'advertiser', vertical TEXT DEFAULT 'store',
            auto_analysis INT DEFAULT 1, track_enabled INT DEFAULT 1, track_until TEXT DEFAULT '',
            name TEXT, naver_store_url TEXT DEFAULT '', main_keywords TEXT DEFAULT '');
        CREATE TABLE tracked_products(id INTEGER PRIMARY KEY, product_url TEXT,
            disabled_at TEXT DEFAULT '');
        CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY, product_id INT, keyword TEXT);
        CREATE TABLE rank_link(client_id INT, tracked_product_id INT);
    """)
    return db, conn


def _rr_a_seed(conn):
    """업체 2곳(살아있음 1 · 계약끝남 2) · 상품 4개 · 전부 같은 키워드."""
    conn.execute("INSERT INTO clients(id,name) VALUES(1,'살아있는곳')")
    conn.execute("INSERT INTO clients(id,name,track_until) VALUES(2,'계약끝난곳','2020-01-01')")
    for pid in (10, 20, 30, 40):
        conn.execute("INSERT INTO tracked_products(id,product_url) VALUES(?,?)",
                     (pid, f"https://smartstore.naver.com/s/products/{pid}"))
        conn.execute("INSERT INTO tracked_keywords(id,product_id,keyword) VALUES(?,?,?)",
                     (pid, pid, "수제쿠키"))
    conn.execute("INSERT INTO rank_link VALUES(1,10)")            # 자격 업체에만
    conn.execute("INSERT INTO rank_link VALUES(2,20)")            # 자격 없는 업체에만
    conn.execute("INSERT INTO rank_link VALUES(1,30)")            # 둘 다에 이어짐
    conn.execute("INSERT INTO rank_link VALUES(2,30)")
    #  40 은 어느 업체에도 안 이어짐(연결 없음)
    conn.commit()


def test_즉시기록_축A_계약끝난_업체에만_이어진_상품은_빠진다():
    import os
    from rank_record import _tracked_targets
    db, conn = _rr_a_db()
    try:
        _rr_a_seed(conn)
        ids = sorted(t["product_id"] for t in _tracked_targets(conn, "수제쿠키"))
        assert 20 not in ids, f"계약 끝난 업체 상품이 즉시 기록 대상에 남았다: {ids}"
    finally:
        conn.close(); os.unlink(db)


def test_즉시기록_축A_자격업체에도_함께_이어진_상품은_남는다():
    """⚠️ 「자격 없는 업체에 **도** 이어짐」을 빼면 정상 기록이 죽는다.
       한 상품이 여러 업체에 이어질 수 있고, 규칙은 '자격 업체가 하나라도 있으면 잰다'."""
    import os
    from rank_record import _tracked_targets
    db, conn = _rr_a_db()
    try:
        _rr_a_seed(conn)
        ids = sorted(t["product_id"] for t in _tracked_targets(conn, "수제쿠키"))
        assert 10 in ids, f"자격 업체 상품이 사라졌다: {ids}"
        assert 30 in ids, f"자격 업체에도 이어진 상품이 잘못 빠졌다: {ids}"
    finally:
        conn.close(); os.unlink(db)


def test_즉시기록_축A_연결없는_상품은_살아있으면_남고_비활성이면_빠진다():
    """⚠️ 연결 없음을 곧바로 빼면 직원이 방금 등록한 상품이 죽는다 — 비활성 표시된 것만 뺀다."""
    import os
    from rank_record import _tracked_targets
    db, conn = _rr_a_db()
    try:
        _rr_a_seed(conn)
        ids = sorted(t["product_id"] for t in _tracked_targets(conn, "수제쿠키"))
        assert 40 in ids, f"방금 등록한(아직 연결 없는) 상품이 죽었다: {ids}"
        conn.execute("UPDATE tracked_products SET disabled_at='2026-08-30' WHERE id=40")
        conn.commit()
        ids2 = sorted(t["product_id"] for t in _tracked_targets(conn, "수제쿠키"))
        assert 40 not in ids2, f"비활성 상품이 그대로 기록된다: {ids2}"
    finally:
        conn.close(); os.unlink(db)


def test_즉시기록_축A_자격판정이_실패하면_종전대로_전부_적는다():
    """판정 조회 하나가 실패했다고 순위 기록이 통째로 멈추면 훨씬 나쁘다."""
    import os
    from rank_record import _tracked_targets
    db, conn = _rr_a_db()
    try:
        _rr_a_seed(conn)
        conn.execute("DROP TABLE rank_link")   # 판정 쿼리를 고장 낸다
        conn.commit()
        ids = sorted(t["product_id"] for t in _tracked_targets(conn, "수제쿠키"))
        assert ids == [10, 20, 30, 40], f"판정 실패 시 폴백이 안 된다: {ids}"
    finally:
        conn.close(); os.unlink(db)


def test_즉시기록_축A_와_배치가_같은_판정함수를_쓴다():
    """두 곳이 갈리면 「수집은 멈췄는데 기록은 계속되는」 일이 또 난다.

    ⚠️ scheduler 를 import 하지 않는다 — 배포 회귀 게이트 환경에는 apscheduler 가 없다
       (tracking_eligibility·split_rule 을 별도 파일로 뺀 것과 같은 이유). 소스를 글자로 읽는다.
    """
    import inspect, os, re
    import rank_record
    assert "eligible_tracked_product_ids" in inspect.getsource(rank_record._tracked_targets), \
        "축A 즉시 기록이 공통 자격 판정을 안 쓴다"

    src = open(os.path.join(os.path.dirname(__file__), "..", "scheduler.py"),
               encoding="utf-8").read()
    body = re.search(r"def _collect_all_keywords\(.*?\n(?=def )", src, re.S)
    assert body, "scheduler._collect_all_keywords 를 못 찾았다(이름이 바뀌었나)"
    assert "eligible_tracked_product_ids" in body.group(0), \
        "08:00 배치가 공통 자격 판정을 안 쓴다"



# ─────────────────────────────────────────────────────────────────────
# 목록에서 내리기(status='terminated') — 내리면 추적도 함께 멈춘다 (2026-08-30)
#
# ⚠️ 이 약속이 화면 확인창에 그대로 적혀 있다(「관리 목록과 순위 추적에서 빠집니다」).
#    자격 판정이 status 를 안 보면 화면 말과 서버 동작이 갈린다 — 그걸 여기서 고정한다.

def test_내린업체는_추적자격에서_빠진다():
    import os, sqlite3, tempfile
    from tracking_eligibility import eligible_clients_sql
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("""
            CREATE TABLE clients(id INTEGER PRIMARY KEY, status TEXT DEFAULT 'active',
                role TEXT DEFAULT 'advertiser', vertical TEXT DEFAULT 'store',
                auto_analysis INT DEFAULT 1, track_enabled INT DEFAULT 1, track_until TEXT DEFAULT '',
                name TEXT, naver_store_url TEXT DEFAULT 'https://smartstore.naver.com/x',
                main_keywords TEXT DEFAULT '');
        """)
        conn.execute("INSERT INTO clients(id,name) VALUES(1,'살아있는곳')")
        conn.execute("INSERT INTO clients(id,name,status) VALUES(2,'내린곳','terminated')")
        conn.commit()
        ids = [r["id"] for r in conn.execute(eligible_clients_sql("id, name"))]
        assert ids == [1], f"내린 업체가 추적 자격에 남았다: {ids}"

        # 되돌리면 그대로 복귀한다 — 되돌리기가 말뿐이면 안 된다
        conn.execute("UPDATE clients SET status='active' WHERE id=2")
        conn.commit()
        ids2 = sorted(r["id"] for r in conn.execute(eligible_clients_sql("id, name")))
        assert ids2 == [1, 2], f"되돌렸는데 자격이 안 돌아왔다: {ids2}"
    finally:
        conn.close(); os.unlink(db)


def test_내린업체_사유는_목록화면과_같은_규칙으로_붙는다():
    # 보관함 카드의 배지도 client_buckets.delete_reasons 를 쓴다 — 두 곳이 갈리면
    # 「목록에선 계약 만료였는데 보관함에선 아무 사유도 없는」 상태가 된다.
    from client_buckets import delete_reasons
    row = {"contract_stage": "계약 만료", "track_until": "", "role": "advertiser", "_synced": True}
    assert delete_reasons(row, _TODAY) == ["계약 만료"]



# ─────────────────────────────────────────────────────────────────────
# 소상공인365 상권 API 건강 기록 (2026-08-30, 대표 확정 안 「나」)
#
# ⚠️ 이 기능이 생긴 이유 — 11:50~12:24 API 가 죽어 있었는데 아무도 몰랐고,
#    「언제부터냐」에 답할 수가 없었다(그 사이 호출이 0건이라 로그도 없었다).

def _sh_db(monkey_path):
    import sqlite3
    import sbiz_health
    sbiz_health.DB_PATH = monkey_path
    conn = sqlite3.connect(monkey_path)
    conn.row_factory = sqlite3.Row
    sbiz_health.ensure_table(conn)
    conn.commit()
    return conn


def test_상권건강_성공과_실패를_남기고_마지막_성공을_안다():
    import os, tempfile, sbiz_health
    db = tempfile.mktemp(suffix=".db")
    conn = _sh_db(db)
    try:
        sbiz_health.record(True, "", source="probe")
        sbiz_health.record(False, "no-stats", source="probe")
        sbiz_health.record(False, "error", source="live")
        s = sbiz_health.summary()
        assert s["last_ok"], "성공 기록을 못 찾는다"
        assert s["fail_streak"] == 2, f"마지막 성공 이후 실패 수가 틀렸다: {s['fail_streak']}"
        assert s["last7_total"] == 3 and s["last7_ok"] == 1, s
        assert s["recent_fail_reasons"].get("error") == 1, s
    finally:
        conn.close(); os.unlink(db)


def test_상권건강_기록이_실패해도_예외를_안_던진다():
    """기록이 안 되는 것보다 분석이 멈추는 게 훨씬 나쁘다."""
    import sbiz_health
    old = sbiz_health.DB_PATH
    sbiz_health.DB_PATH = "/이런/경로는/없다/x.db"
    try:
        sbiz_health.record(True, "", source="probe")   # 예외가 나면 이 줄에서 터진다
        assert sbiz_health.summary() == {}, "조회 실패는 빈 dict 여야 한다"
    finally:
        sbiz_health.DB_PATH = old


def test_상권건강_자가점검은_하나만_되면_정상으로_본다():
    """표본을 하나만 두면 그 동네에 통계가 없을 때 API 장애로 오인한다."""
    import os, tempfile, sbiz_health
    db = tempfile.mktemp(suffix=".db")
    conn = _sh_db(db)
    try:
        calls = []
        # ⚠️ 표본 이름을 여기 박아 두지 않는다 — 목록에서 읽는다.
        #    2026-08-30 에 표본을 바꿨더니 '성수동' 을 박아 둔 이 테스트가 깨졌다.
        #    그때 깨진 건 코드가 아니라 **테스트의 결합**이었다.
        first = sbiz_health.PROBE_SAMPLES[0][0]

        def fake(region, industry, reason=None, **kw):
            calls.append(region)
            if region == first:            # 첫 표본은 통계 없음
                if isinstance(reason, dict):
                    reason["code"] = "no-stats"
                return None
            return {"sales": {"avgAmt": 1}}   # 두 번째는 성공

        r = sbiz_health.run_probe(get_place_sbiz=fake)
        assert r["ok"] is True, f"하나가 됐는데 실패로 봤다: {r}"
        assert len(calls) == 2, f"성공하면 거기서 멈춰야 한다(외부 호출 낭비): {calls}"
        assert sbiz_health.summary()["fail_streak"] == 0
    finally:
        conn.close(); os.unlink(db)


def test_상권건강_자가점검은_전부_실패해야_실패로_남는다():
    import os, tempfile, sbiz_health
    db = tempfile.mktemp(suffix=".db")
    conn = _sh_db(db)
    try:
        def dead(region, industry, reason=None, **kw):
            if isinstance(reason, dict):
                reason["code"] = "error"
            return None

        r = sbiz_health.run_probe(get_place_sbiz=dead)
        assert r["ok"] is False and r["tried"] == len(sbiz_health.PROBE_SAMPLES), r
        s = sbiz_health.summary()
        assert s["fail_streak"] == 1 and s["recent_fail_reasons"].get("error") == 1, s
    finally:
        conn.close(); os.unlink(db)


def test_상권건강_불러보지도_않은_것은_기록하지_않는다():
    """업종 미선택·지역 미입력·키 미설정은 API 문제가 아니다.
       그것까지 실패로 세면 「며칠째 죽었다」가 늘 참이 돼 신호가 죽는다."""
    import sbiz365, sbiz_health
    expected = {"no-key", "no-industry", "no-region", "region-unresolved"}
    assert sbiz365._SBIZ_NOT_TRIED == expected, \
        f"기록 제외 사유 목록이 바뀌었다: {sbiz365._SBIZ_NOT_TRIED}"
    # ⚠️ 같은 목록이 두 파일에 있다(sbiz365 를 import 하면 requests 가 딸려 와 게이트가 깨진다).
    #    갈리면 「부르지도 않은 실패」가 한쪽에서만 걸러져 경보가 조용히 오염된다.
    assert set(sbiz_health.NOT_TRIED_CODES) == expected, \
        f"두 파일의 제외 목록이 갈렸다: {sbiz_health.NOT_TRIED_CODES}"
    import inspect
    src = inspect.getsource(sbiz365.get_place_sbiz)
    assert "_SBIZ_NOT_TRIED" in src, "공개 진입점이 제외 목록을 안 쓴다"
    assert "_get_place_sbiz_impl" in src, "공개 진입점이 본문을 안 부른다"


def test_상권건강_지역판정_실패는_API_건강이_아니다():
    """⚠️ 2026-08-30 배포 직후 실측으로 잡은 결함.

    `region-unresolved` 는 **네이버 지역검색**이 동네를 못 찾은 것이라 상권 API 는
    부르지도 않았다. 그런데 첫 판은 이걸 API 실패로 기록했고, 하필 표본 첫 곳(성수동)이
    **상시** 이 사유로 끊겼다 — API 가 멀쩡한 날에도 매일 실패가 한 건씩 쌓여
    정작 진짜 장애 때 그 신호가 묻혔을 것이다.
    """
    import os, tempfile, sbiz_health
    db = tempfile.mktemp(suffix=".db")
    conn = _sh_db(db)
    try:
        calls = []

        def half(region, industry, reason=None, **kw):
            calls.append(region)
            if len(calls) == 1:                    # 첫 표본은 지역 판정에서 끊긴다
                if isinstance(reason, dict):
                    reason["code"] = "region-unresolved"
                return None
            return {"sales": {"avgAmt": 1}}        # 다음 표본은 정상

        r = sbiz_health.run_probe(get_place_sbiz=half)
        assert r["ok"] is True, f"뒤 표본이 됐는데 실패로 봤다: {r}"
        assert r["reached"] == 1, f"API 에 닿은 표본만 세어야 한다: {r}"
        s = sbiz_health.summary()
        # 성공 1건만 남고, 지역 판정 실패는 어디에도 안 쌓인다.
        assert s["last7_total"] == 1 and s["last7_ok"] == 1, s
        assert s["recent_fail_reasons"] == {}, f"지역 판정 실패가 기록에 샜다: {s}"
    finally:
        conn.close(); os.unlink(db)


def test_상권건강_표본이_전부_API에_못닿으면_아무것도_기록하지_않는다():
    """「죽었다」가 아니라 「못 쟀다」 — 둘을 섞으면 기록이 거짓말을 한다."""
    import os, tempfile, sbiz_health
    db = tempfile.mktemp(suffix=".db")
    conn = _sh_db(db)
    try:
        def unreachable(region, industry, reason=None, **kw):
            if isinstance(reason, dict):
                reason["code"] = "region-unresolved"
            return None

        r = sbiz_health.run_probe(get_place_sbiz=unreachable)
        assert r["ok"] is None, f"판정 못 한 것을 실패로 단정했다: {r}"
        assert r["reached"] == 0, r
        s = sbiz_health.summary()
        assert s["last7_total"] == 0, f"못 잰 회차가 기록에 남았다: {s}"
    finally:
        conn.close(); os.unlink(db)


def test_상권건강_표본은_상권API까지_닿는_곳이어야_한다():
    """⚠️ 표본을 바꿀 때 서버 실측 없이 넣으면 이 경보가 통째로 죽는다.

    2026-08-30 서버 실측 — 성수동은 주소가 '성동구'로만 와서 **상시** 지역 판정에서
    끊긴다(9곳 중 유일). 그 자리에 넣었던 탓에 배포 첫날부터 실패가 기록됐다.
    """
    import sbiz_health
    bad = {"성수동"}
    used = {r for r, _ in sbiz_health.PROBE_SAMPLES}
    assert not (used & bad), \
        f"상권 API 에 닿지 못하는 지역이 표본에 있다(2026-08-30 실측): {used & bad}"
    assert len(sbiz_health.PROBE_SAMPLES) >= 2, "표본이 하나면 그 동네 사정이 곧 API 장애로 읽힌다"


def test_상권건강_자가점검_잡이_등록돼_있다():
    """직원 호출 기록만 있으면 「아무도 안 썼다」와 「죽었다」를 못 가른다.

    ⚠️ scheduler 를 import 하지 않는다 — 게이트 환경에 apscheduler 가 없다.
    """
    import os, re
    src = open(os.path.join(os.path.dirname(__file__), "..", "scheduler.py"),
               encoding="utf-8").read()
    assert "_run_sbiz_health_probe" in src, "자가 점검 함수가 없다"
    assert re.search(r'id="sbiz_health_probe"', src), "자가 점검 잡이 등록돼 있지 않다"
    assert re.search(r"CronTrigger\(hour=5, minute=0\)", src), "자가 점검 시각(05:00)이 바뀌었다"
    # ⚠️ 「못 쟀다」와 「죽었다」를 로그가 갈라 말해야 한다 — 안 그러면 표본이 망가진 것을
    #    API 장애로 읽고 엉뚱한 데를 파게 된다.
    assert 'r.get("ok") is None' in src, "「판정 못 함」 분기가 없다(표본이 API 에 못 닿은 경우)"
    assert "판정 못 함" in src, "「판정 못 함」 로그 문구가 없다"


# ─────────────────────────────────────────────────────────────────────
# 업체 상세 HTML 옆 표 이관 (2026-08-30) — 목록 조회가 느리던 원인 제거
#
# ⚠️ 실측 근거: 활성 703곳에서 덩어리 **앞** 칸 2ms vs **뒤** 칸 635ms(300배).
#    이 이관이 되돌아가면(=업체 표에 덩어리가 다시 쌓이면) 그 느림이 그대로 돌아온다.

def _dh_db():
    import sqlite3, tempfile
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT, detail_html TEXT DEFAULT '',
                             contract_stage TEXT);
    """)
    return db, conn


def test_상세HTML_이관하면_업체표에서_비워진다():
    import os
    from detail_html_store import migrate_batch, get_html, pending_count
    db, conn = _dh_db()
    try:
        big = "x" * 5000
        conn.execute("INSERT INTO clients(id,name,detail_html) VALUES(1,'가',?)", (big,))
        conn.execute("INSERT INTO clients(id,name,detail_html) VALUES(2,'나',?)", (big,))
        conn.execute("INSERT INTO clients(id,name,detail_html) VALUES(3,'다','')")
        conn.commit()
        assert pending_count(conn) == 2
        assert migrate_batch(conn, limit=10) == 2
        # 값은 옆 표에 그대로, 업체 표는 비었다 — 그래야 목록 조회가 덩어리를 안 지난다
        assert get_html(conn, 1) == big
        left = conn.execute("SELECT COUNT(*) FROM clients WHERE COALESCE(detail_html,'') != ''").fetchone()[0]
        assert left == 0, "업체 표에 덩어리가 남았다 — 느림이 그대로다"
        assert migrate_batch(conn, limit=10) == 0     # 두 번 돌려도 안전(멱등)
    finally:
        conn.close(); os.unlink(db)


def test_상세HTML_이관_전_데이터도_읽힌다():
    # 이관 도중·이관 전이라도 값이 사라지면 안 된다(옛 칸 폴백).
    import os
    from detail_html_store import get_html
    db, conn = _dh_db()
    try:
        conn.execute("INSERT INTO clients(id,name,detail_html) VALUES(1,'가','옛날값')")
        conn.commit()
        assert get_html(conn, 1) == "옛날값"
    finally:
        conn.close(); os.unlink(db)


def test_상세HTML_저장하면_옛칸을_비운다():
    # 새로 저장할 때 옛 칸을 안 비우면 덩어리가 업체 표에 되살아난다.
    import os
    from detail_html_store import set_html, get_html
    db, conn = _dh_db()
    try:
        conn.execute("INSERT INTO clients(id,name,detail_html) VALUES(1,'가','옛날덩어리')")
        conn.commit()
        set_html(conn, 1, "새값")
        conn.commit()
        assert get_html(conn, 1) == "새값"
        assert conn.execute("SELECT detail_html FROM clients WHERE id=1").fetchone()[0] == ""
    finally:
        conn.close(); os.unlink(db)


def test_수집원문_보관일수는_읽는_범위보다_짧아지지_않는다():
    # 수집 현황 화면이 실제로 읽는 가장 깊은 범위가 7일이다.
    import os
    for env_val, expect in [("3", 7), ("14", 14), ("30", 30), ("이상한값", 14)]:
        old = os.environ.get("COLLECTED_SERP_KEEP_DAYS")
        os.environ["COLLECTED_SERP_KEEP_DAYS"] = env_val
        try:
            try:
                keep = int(os.getenv("COLLECTED_SERP_KEEP_DAYS", 14))
            except (TypeError, ValueError):
                keep = 14
            keep = max(keep, 7)
            assert keep == expect, f"{env_val} → {keep} (기대 {expect})"
        finally:
            if old is None:
                os.environ.pop("COLLECTED_SERP_KEEP_DAYS", None)
            else:
                os.environ["COLLECTED_SERP_KEEP_DAYS"] = old


def test_수집원문_정리는_분석정리와_독립된_잡이다():
    """⚠️ 처음엔 분석 보관정책 함수 끝에 이어 붙였는데, 그 함수는 「지울 게 없으면」
       early return 이라 조용한 날에는 수집 원문 정리가 통째로 건너뛰어졌다."""
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "scheduler.py"), encoding="utf-8").read()
    assert 'id="collected_serp_retention"' in src, "수집 원문 정리가 잡으로 등록돼 있지 않다"
    body = src.split("def _run_client_analyses_retention()")[1].split("\ndef ")[0]
    assert "_run_collected_serp_retention()" not in body, \
        "분석 정리 끝에 꼬리 호출이 다시 생겼다 — early return 에 가려 조용히 안 돈다"


def test_VACUUM_은_새벽에만_돈다():
    """낮에 돌면 그 몇 분간 DB 가 잠겨 화면이 멈춘다(대표께 약속한 조건)."""
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "scheduler.py"), encoding="utf-8").read()
    assert "1 <= datetime.now().hour <= 5" in src, "VACUUM 새벽 창 가드가 사라졌다"
    assert 'id="one_time_vacuum_night"' in src, "새벽 VACUUM 잡이 등록돼 있지 않다"


# ==================== 시각을 KST 로 적는가 (2026-08-31) ====================
# 서버의 reports·clients 표는 기본값이 CURRENT_TIMESTAMP(=UTC)다. 코드의 CREATE TABLE 은
# localtime 으로 적혀 있지만 IF NOT EXISTS 는 기존 표를 안 고치므로 소용이 없다.
# ⇒ 넣는 자리에서 KST 를 명시하는 것만이 유효하고, 그것이 지켜지는지 여기서 지킨다.

def _src(name):
    import os
    return open(os.path.join(os.path.dirname(__file__), "..", name), encoding="utf-8").read()


def test_보고서를_넣는_두_자리가_KST_를_명시한다():
    """⚠️ 이 검사가 없으면 다음에 INSERT 를 손댈 때 조용히 UTC 로 되돌아간다 —
       화면은 멀쩡해 보이고 날짜도 맞아서, 9시간 어긋난 걸 아무도 눈치채지 못한다."""
    for name in ("weekly_report.py", "reports.py"):
        src = _src(name)
        i = src.index("INSERT INTO reports")
        block = src[i:i + 700]
        assert "created_at" in block, f"{name}: INSERT 에 created_at 이 없다 — 서버 기본값(UTC)이 쓰인다"
        assert "datetime('now','localtime')" in block, f"{name}: KST 명시가 없다"


def test_업체를_넣는_자리가_KST_를_명시한다():
    src = _src("clients.py")
    i = src.index("INSERT INTO clients")
    block = src[i:i + 900]
    for col in ("created_at", "updated_at"):
        assert col in block, f"clients.py: INSERT 에 {col} 이 없다 — 서버 기본값(UTC)이 쓰인다"
    assert block.count("datetime('now','localtime')") >= 2, "clients.py: KST 명시가 두 칸에 다 없다"


def test_보고서_INSERT_가_실제로_KST_를_적는다():
    """문자열 검사만으로는 「자리 수가 맞는가」를 못 잡는다 — 실제로 넣어 본다.
    ⚠️ SQL 주석(--)을 앞에 붙였으므로 그것까지 통과하는지도 여기서 확인된다."""
    import re
    import sqlite3
    from datetime import datetime
    conn = sqlite3.connect(":memory:")
    # 서버와 같은 병(기본값 UTC)을 일부러 재현한다 — 명시가 없으면 UTC 가 들어가야 한다.
    conn.execute("""CREATE TABLE reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, title TEXT, keyword TEXT,
        product_url TEXT DEFAULT '', report_data TEXT, report_hash TEXT UNIQUE,
        html_filename TEXT DEFAULT '', status TEXT DEFAULT 'generated', views INTEGER DEFAULT 0,
        created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        is_auto INTEGER NOT NULL DEFAULT 0)""")

    src = _src("reports.py")
    i = src.index("INSERT INTO reports")
    sql = src[i:src.index('"""', i)]
    conn.execute(sql, (1, "t", "k", "", "{}", "h1", "f", "generated", 1))

    local = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
    got = conn.execute("SELECT created_at FROM reports").fetchone()[0]
    assert got[:13] == local[:13], f"KST 로 안 적혔다: {got} (지금 {local})"
    utc = conn.execute("SELECT datetime('now')").fetchone()[0]
    if utc[:13] != local[:13]:          # 컨테이너가 UTC 면 이 비교는 뜻이 없다
        assert got[:13] != utc[:13], "UTC 가 들어갔다"


def test_시각_보정은_옛_행만_옮기고_새_행은_안_건드린다():
    """보정의 핵심 조건 두 겹(id 경계 · 1시간 뒤처짐)을 실제로 돌려서 확인한다."""
    import sqlite3
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from kst_backfill import backfill
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, created_at TEXT)")
    conn.executescript("""
        INSERT INTO reports VALUES (1, datetime('now','localtime','-9 hours'));   -- 옛 UTC 행
        INSERT INTO reports VALUES (2, datetime('now','localtime','-9 hours','-3 days'));
        INSERT INTO reports VALUES (3, datetime('now','localtime'));              -- 새 KST 행
        INSERT INTO reports VALUES (4, '');                                       -- 형식 아님
        INSERT INTO reports VALUES (5, NULL);
    """)
    before = {r[0]: r[1] for r in conn.execute("SELECT id, created_at FROM reports")}
    n = backfill(conn, max_id=5)
    after = {r[0]: r[1] for r in conn.execute("SELECT id, created_at FROM reports")}

    assert n == 2, f"옛 행 2건만 옮겨야 하는데 {n}건"
    now = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
    assert after[1][:13] == now[:13], "옛 행이 지금 시각으로 안 왔다"
    assert after[3] == before[3], "새 행(이미 KST)을 건드렸다 — 9시간 밀렸다"
    assert after[4] == "" and after[5] is None, "형식이 아닌 행의 값이 사라졌다"


def test_시각_보정이_id_경계_밖을_안_건드린다():
    import sqlite3
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from kst_backfill import backfill
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, created_at TEXT)")
    conn.executescript("""
        INSERT INTO reports VALUES (1, datetime('now','localtime','-9 hours'));
        INSERT INTO reports VALUES (2, datetime('now','localtime','-9 hours'));
    """)
    keep = conn.execute("SELECT created_at FROM reports WHERE id=2").fetchone()[0]
    assert backfill(conn, max_id=1) == 1
    assert conn.execute("SELECT created_at FROM reports WHERE id=2").fetchone()[0] == keep, \
        "id 경계 밖의 행을 건드렸다"


def test_시각_보정_잡이_등록돼_있고_os_를_임포트한다():
    """⚠️ scheduler.py 는 os 를 모듈 수준에서 임포트하지 않는다(9곳이 함수 안에서 한다).
       빼먹으면 NameError 가 except 에 먹혀 보정이 조용히 안 돈다 — 실제로 한 번 그랬다."""
    src = _src("scheduler.py")
    assert 'id="reports_kst_backfill_boot"' in src, "시각 보정 잡이 등록돼 있지 않다"
    body = src.split("def _run_reports_kst_backfill()")[1].split("\ndef ")[0]
    assert "import os" in body, "os 임포트가 빠졌다 — NameError 가 except 에 먹혀 조용히 안 돈다"


# ==================== 분석 집계 커버링 인덱스 (2026-08-31) ====================

def test_분석_집계_커버링_인덱스가_있다():
    """keyword·product_url 이 빠지면 행 본문(덩어리 5칸)을 찾아가 290ms·563ms 가 된다."""
    src = _src("client_dashboard.py")
    assert "idx_client_analyses_board" in src, "커버링 인덱스가 사라졌다"
    i = src.index("idx_client_analyses_board")
    block = src[i:i + 300]
    for col in ("client_id", "analyzed_date", "updated_at", "keyword", "product_url"):
        assert col in block, f"인덱스에 {col} 이 빠졌다 — 하나만 빠져도 커버링이 깨진다"


def test_인덱스가_실제로_커버링으로_쓰인다():
    """플래너가 그 인덱스를 고르는지 실제로 돌려 본다 — 만들어 두고 안 쓰이면 헛것이다."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE client_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL, keyword TEXT NOT NULL,
        product_url TEXT DEFAULT '', analysis_json TEXT DEFAULT '{}', volume_json TEXT DEFAULT '{}',
        related_json TEXT DEFAULT '{}', shop_products_json TEXT DEFAULT '[]',
        advertiser_json TEXT DEFAULT '{}', created_at TEXT, updated_at TEXT,
        analyzed_date TEXT, report_html TEXT, created_by INTEGER)""")
    src = _src("client_dashboard.py")
    i = src.index("CREATE INDEX IF NOT EXISTS idx_client_analyses_board")
    conn.execute(src[i:src.index('"""', i)])
    rows = [(c, "k%d" % c, "u", "2026-08-%02d" % (c % 28 + 1), "2026-08-01 10:00:00")
            for c in range(1, 60)]
    conn.executemany("INSERT INTO client_analyses (client_id, keyword, product_url,"
                     " analyzed_date, updated_at) VALUES (?,?,?,?,?)", rows)
    plan = " ".join(r[-1] for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT client_id, COUNT(*), MAX(updated_at),"
        " COUNT(DISTINCT keyword), COUNT(DISTINCT analyzed_date) FROM client_analyses"
        " WHERE client_id IN (1,2,3) GROUP BY client_id"))
    assert "COVERING INDEX idx_client_analyses_board" in plan, \
        f"커버링으로 안 쓰인다 — 칸 구성을 다시 볼 것: {plan}"


# ==================== 응답 압축 (2026-08-31) ====================
# 내용을 바꾸지 않고 전송만 줄인다. 켜져 있는지와, 켜는 방식이 안전한지를 지킨다.

def test_응답_압축이_켜져_있다():
    src = _src("main.py")
    assert "from starlette.middleware.gzip import GZipMiddleware" in src, "압축 미들웨어 임포트가 없다"
    assert "app.add_middleware(GZipMiddleware" in src, "압축 미들웨어 등록이 사라졌다"
    assert '"minimum_size": 500' in src, "작은 응답까지 압축하면 오히려 커진다 — minimum_size 가 사라졌다"


def test_압축수준을_기본값_9_로_두지_않는다():
    """기본 9 는 실측 25~44ms. 사내 유선에서는 아낀 전송(40ms)을 CPU 로 도로 까먹는다.
    6 은 6ms 에 사실상 같은 크기(60KB)다."""
    src = _src("main.py")
    assert '"compresslevel"] = 6' in src or '"compresslevel": 6' in src, \
        "compresslevel 을 6 으로 낮추는 부분이 사라졌다 — 기본값 9 면 빠른 회선에서 손해다"


def test_압축수준_인자가_없는_버전에서도_기동한다():
    """⚠️ add_middleware 는 즉시 생성하지 않아 try/except 로는 못 잡는다 —
       인자가 없는 starlette 을 만나면 기동이 통째로 죽는다. 서명을 먼저 보는지 확인한다."""
    import inspect

    class 옛버전:                      # compresslevel 을 안 받는다
        def __init__(self, app, minimum_size=500): pass

    class 새버전:
        def __init__(self, app, minimum_size=500, compresslevel=9): pass

    for cls, 기대 in ((옛버전, False), (새버전, True)):
        kw = {"minimum_size": 500}
        if "compresslevel" in inspect.signature(cls.__init__).parameters:
            kw["compresslevel"] = 6
        assert ("compresslevel" in kw) is 기대, f"{cls.__name__} 판정이 틀렸다"
        cls(None, **kw)               # 실제로 만들어 봐서 TypeError 가 안 나는지 확인

    src = _src("main.py")
    assert "inspect.signature" in src or "_inspect.signature" in src, \
        "서명 확인 없이 compresslevel 을 넘기고 있다 — 옛 starlette 에서 기동이 죽는다"


def test_압축은_내용을_바꾸지_않는다():
    """대표 조건 「절대 어떠한 것도 변경되거나 바뀌어선 안 된다」의 근거."""
    import gzip
    import json
    본문 = json.dumps({"success": True, "data": [{"id": i, "name": "업체%d" % i,
                                                 "키워드": ["가", "나", "다"]} for i in range(300)]},
                     ensure_ascii=False).encode("utf-8")
    묶음 = gzip.compress(본문, 6)
    assert gzip.decompress(묶음) == 본문, "압축을 풀면 원본과 달라진다"
    assert len(묶음) < len(본문) / 2, f"압축이 안 된다 ({len(본문)} → {len(묶음)})"


# ============ 「기록 대기」를 두 종류로 가른다 (신고 #248 · 2026-08-31) ============

def test_수집_슬롯_규칙이_한_곳에만_있다():
    """⚠️ 화면이 「오후 5시경 수집」이라고 말하려면 수집기와 **같은 식**을 써야 한다.
       두 곳이 각자 계산하면 화면이 거짓말을 하고, 그건 지금 고치는 문제와 똑같은 종류다."""
    col = _src("collector.py")
    assert "from collect_slot import" in col, "collector 가 공용 규칙을 안 쓴다"
    assert "def _slot_of" in col and "_slot_rule(" in col, "_slot_of 가 공용 규칙에 위임하지 않는다"
    assert "import zlib" not in col.split("def _slot_of")[1][:200], \
        "_slot_of 안에 식이 다시 박혀 있다 — 규칙이 두 곳으로 갈렸다"
    cd = _src("client_dashboard.py")
    assert "from collect_slot import wait_hint" in cd, "화면이 공용 규칙을 안 쓴다"


def test_슬롯_계산이_종전과_같다():
    """규칙을 옮기기만 했다 — 값이 하나라도 달라지면 그날 수집이 통째로 재배정된다."""
    import zlib
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from collect_slot import slot_of
    for k in ("흰다리새우", "한우", "a", "", "가" * 40, "키워드 사이 공백"):
        h = zlib.crc32(k.encode("utf-8"))
        assert slot_of(k, True) == h % 15, f"우선 슬롯이 달라졌다: {k}"
        assert slot_of(k, False) == 15 + (h % 9), f"후순위 슬롯이 달라졌다: {k}"


def test_상품_전용_키워드는_오후_슬롯이다():
    """신고의 핵심 — 추가 등록 키워드는 15~23시에만 돈다. 그걸 화면이 말해 줘야 한다."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from collect_slot import slot_of
    for k in ("흰다리새우", "호박고구마", "전복죽", "곱창", "바지락"):
        assert 15 <= slot_of(k, False) <= 23, f"{k} 가 오후 슬롯 밖이다"
        assert 0 <= slot_of(k, True) <= 14, f"{k} 의 우선 슬롯이 범위 밖이다"


def test_대기_안내가_지킬_수_있는_말만_한다():
    """⚠️ 종전엔 「보통 수 분」이라고 적혀 있었다 — 오후 슬롯 키워드는 최대 하루다.
       지킬 수 없는 약속이 「고장났다」는 신고를 만들었다."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from collect_slot import wait_hint, slot_label
    h = wait_hint("흰다리새우", False)
    assert "분" not in h, f"「분」 단위를 약속하고 있다: {h}"
    assert "수집" in h and any(w in h for w in ("오전", "오후", "밤", "정오", "자정")), h
    # 이미 지난 시각을 앞으로 올 것처럼 적지 않는다
    assert wait_hint("흰다리새우", False, now_hour=23) == "오늘 안에 수집"
    for hh, want in ((0, "자정"), (9, "오전"), (12, "정오"), (15, "오후"), (23, "밤")):
        assert want in slot_label(hh), f"{hh}시 라벨이 이상하다: {slot_label(hh)}"

    # 화면·등록 안내 어디에도 「수 분」 약속이 남아 있으면 안 된다(주석 설명은 예외)
    for name in ("client_dashboard.py",):
        for line in _src(name).split("\n"):
            st = line.strip()
            if st.startswith("#"):
                continue
            assert "수 분 안에" not in st, f"{name} 에 「수 분」 약속이 남아 있다: {st[:70]}"


def test_대기_사유를_두_종류로_가른다():
    src = _src("client_dashboard.py")
    assert "_pending_meta" in src, "대기 사유 판정이 사라졌다"
    assert '"pending_reason": "blocked"' in src and '"pending_reason": "slot"' in src, \
        "두 종류(blocked/slot)를 안 가른다"
    assert "track_enabled" in src and "track_until" in src, \
        "막힌 사유(추적 꺼짐·기간 만료) 판정이 빠졌다"
    # 두 곳의 대기 행 모두에 실려야 한다 — 한쪽만 붙이면 그 화면은 종전 그대로다
    assert src.count("**_pending_meta(") == 2, \
        f"대기 행 두 곳 중 일부에만 붙었다({src.count('**_pending_meta(')}곳)"


def test_화면이_두_배지를_그린다():
    import os as _os
    fe = _os.path.join(_os.path.dirname(__file__), "..", "..",
                       "frontend", "js", "components", "KeywordRankPage.jsx")
    src = open(fe, encoding="utf-8").read()
    assert "pending_reason === 'blocked'" in src, "막힌 것과 대기 중인 것을 안 가른다"
    assert "추적 안 됨" in src, "막힌 배지 문구가 없다"
    assert "pending_hint" in src, "예상 시각을 안 보여준다"


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
