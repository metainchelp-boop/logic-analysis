"""신고 #246: 브랜드스토어 상세 파서와 전용 API 경계를 결정적으로 검증한다.

실행: python backend/tests/test_brand_store_parser.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests as _requests  # noqa: E402


def _no_net(*_args, **_kwargs):
    raise RuntimeError("network disabled in tests")


_requests.get = _no_net
_requests.post = _no_net

import naver_crawler as nc  # noqa: E402


def test_naver_store_slug_requires_exact_supported_host():
    """스마트·브랜드스토어 슬러그만 읽고 유사/악성 호스트는 거부한다."""
    supported = {
        "https://smartstore.naver.com/example/products/12345": "example",
        "https://m.smartstore.naver.com/example/products/12345": "example",
        "https://brand.naver.com/vayapet/products/9864738770": "vayapet",
        "https://m.brand.naver.com/vayapet/products/9864738770": "vayapet",
    }
    for url, expected in supported.items():
        assert nc.extract_store_name_from_url(url) == expected, url

    rejected = (
        "https://brand.naver.com.evil.example/vayapet/products/9864738770",
        "https://brand.naver.com@evil.example/vayapet/products/9864738770",
        "https://evil.example/?next=https://brand.naver.com/vayapet/products/9864738770",
        "https://notbrand.naver.com/vayapet/products/9864738770",
        "ftp://brand.naver.com/vayapet/products/9864738770",
    )
    for url in rejected:
        assert nc.extract_store_name_from_url(url) is None, url


def test_review_count_api_is_smartstore_only():
    """브랜드 URL을 스마트스토어 내부 리뷰 API로 바꿔 호출하지 않는다."""
    calls = []

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"reviewAmount": {"totalReviewCount": 12}}

    original_get = nc.requests.get
    nc.requests.get = lambda url, **kwargs: calls.append(url) or _Response()
    try:
        assert nc.get_review_count(
            "https://smartstore.naver.com/example/products/12345"
        ) == 12
        assert calls == [
            "https://smartstore.naver.com/i/v1/stores/example/products/12345"
        ]

        calls.clear()
        assert nc.get_review_count(
            "https://brand.naver.com/vayapet/products/9864738770"
        ) is None
        assert calls == [], calls
    finally:
        nc.requests.get = original_get


def test_smartstore_detail_api_skips_brand_url():
    """스마트스토어 JSON API 폴백도 브랜드 URL에는 호출되지 않는다."""
    calls = []
    original_get = nc.requests.get
    nc.requests.get = lambda url, **kwargs: calls.append(url)
    try:
        assert nc._extract_smartstore_info(
            "https://brand.naver.com/vayapet/products/9864738770"
        ) == (None, None)
        assert nc._fetch_smartstore_api(
            "https://brand.naver.com/vayapet/products/9864738770"
        ) is None
        assert calls == [], calls
    finally:
        nc.requests.get = original_get


def test_brand_store_preloaded_detail_data():
    """브랜드 캡처에서도 가격·카테고리·리뷰·평점·스토어를 보존한다."""
    html = r'''
        <!DOCTYPE html><html><head>
        <meta name="api-wish-count" content="17">
        </head><body>
        <div class="product-detail">배송비 무료 · 교환 및 반품 · 구매후기</div>
        <script>
        window.__PRELOADED_STATE__={
          "simpleProductForDetailPage":{
            "id":9864738770,
            "category":{
              "wholeCategoryName":"생활\u002F건강\u003E반려동물\u003E강아지 간식\u003E동결건조 간식",
              "categoryName":"동결건조 간식"
            },
            "name":"바야 강아지 방울양배추 35g 동결건조 야채 비건 트릿 강아지 애견 간식",
            "channel":{"channelName":"Vaya"},
            "salePrice":12300,
            "benefitsView":{"discountedSalePrice":12300},
            "reviewAmount":{"totalReviewCount":540,"averageReviewScore":4.88},
            "notApplicable":undefined
          },
          "unavailableSection":undefined
        };
        </script></body></html>
    '''

    result = nc.analyze_detail_page(
        html,
        "https://brand.naver.com/vayapet/products/9864738770",
    )
    review = (result or {}).get("reviewData") or {}
    assert review.get("price") == 12300, review
    assert review.get("category") == "생활/건강>반려동물>강아지 간식>동결건조 간식", review
    assert review.get("category1") == "생활/건강", review
    assert review.get("reviewCount") == 540, review
    assert review.get("rating") == 4.88, review
    assert (result.get("storeInfo") or {}).get("name") == "Vaya", result.get("storeInfo")


def test_smartstore_next_data_detail_data_unchanged():
    """브랜드 폴백 추가 후에도 기존 스마트스토어 NEXT_DATA를 우선 보존한다."""
    html = '''
        <!DOCTYPE html><html><head>
        <meta name="api-wish-count" content="8">
        <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"product":{
          "discountedSalePrice":9900,
          "category":{"wholeCategoryName":"식품>과자>쿠키"}
        }}}}
        </script></head><body><div class="product-detail">상품 상세</div></body></html>
    '''

    result = nc.analyze_detail_page(
        html,
        "https://smartstore.naver.com/example/products/12345",
    )
    review = (result or {}).get("reviewData") or {}
    assert review.get("price") == 9900, review
    assert review.get("category") == "식품>과자>쿠키", review
    assert review.get("category1") == "식품", review


if __name__ == "__main__":
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
