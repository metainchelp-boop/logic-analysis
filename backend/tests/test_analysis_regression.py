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
