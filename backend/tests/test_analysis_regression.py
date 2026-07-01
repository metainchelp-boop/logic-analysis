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
