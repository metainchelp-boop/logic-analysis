"""신고 #246: 브랜드스토어가 네이버 스토어 점수 정책에서 불이익을 받지 않는지 검증.

실행: python backend/tests/test_brand_store_scoring.py
"""
from pathlib import Path
import os
import sys
import tempfile
import types


_TMP_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", str(Path(_TMP_DIR.name) / "logic.db"))
os.environ.setdefault("REPORTS_DIR", str(Path(_TMP_DIR.name) / "reports"))
os.environ.setdefault("DEV_MODE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# 로컬 최소 테스트 환경에 APScheduler가 없을 때도 라우트의 순수 계산 경로를
# 검증할 수 있게 임포트 계약만 제공한다. 운영/CI에는 requirements의 실제 패키지를 쓴다.
try:
    import apscheduler  # noqa: F401
except ModuleNotFoundError:
    apscheduler_pkg = types.ModuleType("apscheduler")
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    background_pkg = types.ModuleType("apscheduler.schedulers.background")
    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_pkg = types.ModuleType("apscheduler.triggers.cron")
    interval_pkg = types.ModuleType("apscheduler.triggers.interval")

    class _UnusedScheduler:
        pass

    class _UnusedTrigger:
        def __init__(self, *args, **kwargs):
            pass

    background_pkg.BackgroundScheduler = _UnusedScheduler
    cron_pkg.CronTrigger = _UnusedTrigger
    interval_pkg.IntervalTrigger = _UnusedTrigger
    sys.modules.update({
        "apscheduler": apscheduler_pkg,
        "apscheduler.schedulers": schedulers_pkg,
        "apscheduler.schedulers.background": background_pkg,
        "apscheduler.triggers": triggers_pkg,
        "apscheduler.triggers.cron": cron_pkg,
        "apscheduler.triggers.interval": interval_pkg,
    })


from main import (  # noqa: E402
    DetailPageAnalysisRequest,
    SeoAnalysisRequest,
    detail_page_analyze,
    seo_analyze,
)
import main as main_module  # noqa: E402


def _analyze(url):
    product = {
        "product_name": "방울양배추 동결건조 강아지 간식",
        "price": 12300,
        "brand": "바야",
        "store_name": "바야 프리미엄 펫푸드",
        "category1": "생활/건강",
        "category2": "반려동물",
    }
    competitor = dict(product, product_url=url, product_id="9864738770", rank=5)
    req = SeoAnalysisRequest(
        product_url=url,
        keyword="방울양배추",
        cached_rank=5,
        cached_product_info=dict(product),
        cached_competitors=[competitor],
        cached_total_volume=1000,
        cached_review_count=540,
        cached_rating=4.88,
    )
    return seo_analyze(req, current_user={"id": 1})["data"]


def test_brand_store_uses_same_naver_store_scoring_as_smartstore():
    smart = _analyze("https://smartstore.naver.com/vayapet/products/9864738770")
    brand = _analyze("https://brand.naver.com/vayapet/products/9864738770")

    assert brand["scores"]["brand"] == smart["scores"]["brand"] == 100
    assert brand["scores"]["naverpay"] == smart["scores"]["naverpay"] == 100
    assert brand["scores"]["detail"]["has_naverpay"] is True
    assert brand["scores"]["total"] == smart["scores"]["total"]
    assert not any("네이버페이 연동" in item for item in brand["suggestions"])


def test_mobile_brand_store_is_also_a_naver_store_without_changing_legacy_flag():
    mobile = _analyze("https://m.brand.naver.com/vayapet/products/9864738770/")
    detail = mobile["scores"]["detail"]

    assert detail["is_naver_store"] is True
    assert detail["is_smartstore"] is False
    assert detail["has_naverpay"] is True


def test_mobile_smartstore_keeps_its_existing_platform_and_legacy_flags():
    mobile = _analyze("https://m.smartstore.naver.com/vayapet/products/9864738770/")
    detail = mobile["scores"]["detail"]

    assert detail["is_naver_store"] is True
    assert detail["is_smartstore"] is True
    assert detail["has_naverpay"] is True


def test_non_http_brand_url_gets_no_naver_store_credit():
    external = _analyze("ftp://brand.naver.com/vayapet/products/9864738770")

    assert external["scores"]["brand"] == 70
    assert external["scores"]["naverpay"] == 50
    assert external["scores"]["detail"]["is_naver_store"] is False


def test_naver_store_text_in_an_unrelated_host_does_not_receive_platform_credit():
    external = _analyze(
        "https://mall.example/products/9864738770?next=https://smartstore.naver.com/vayapet"
    )

    assert external["scores"]["brand"] == 70
    assert external["scores"]["naverpay"] == 50
    assert external["scores"]["detail"]["is_naver_store"] is False
    assert external["scores"]["detail"]["has_naverpay"] is False


def test_naver_store_credit_requires_exact_product_path_and_ignores_normal_query_hash():
    accepted_urls = (
        "https://brand.naver.com/vayapet/products/9864738770?foo=1",
        "https://brand.naver.com/vayapet/products/9864738770#detail",
        "https://brand.naver.com/vayapet/products/9864738770?NaPm=tracking#detail",
    )
    for url in accepted_urls:
        result = _analyze(url)
        detail = result["scores"]["detail"]
        assert result["scores"]["brand"] == 100, url
        assert result["scores"]["naverpay"] == 100, url
        assert detail["is_naver_store"] is True, url
        assert detail["has_naverpay"] is True, url

    rejected_urls = (
        "https://brand.naver.com/",
        "https://brand.naver.com/vayapet",
        "https://brand.naver.com/vayapet/products/not-a-number",
        "https://brand.naver.com/vayapet/products/9864738770/reviews",
        "https://brand.naver.com/?next=/vayapet/products/9864738770",
        "https://brand.naver.com:443/vayapet/products/9864738770",
        "https://smartstore.naver.com/example/products/12345/reviews",
    )

    for url in rejected_urls:
        result = _analyze(url)
        detail = result["scores"]["detail"]
        assert result["scores"]["brand"] == 70, url
        assert result["scores"]["naverpay"] == 50, url
        assert detail["is_naver_store"] is False, url
        assert detail["has_naverpay"] is False, url
        assert detail["is_smartstore"] is False, url


def test_malformed_url_remains_a_safe_non_naver_store_input():
    malformed = _analyze("https://[broken/products/9864738770")

    assert malformed["scores"]["naverpay"] == 50
    assert malformed["scores"]["detail"]["is_naver_store"] is False


def test_brand_store_slug_fallback_enriches_cached_product_name():
    req = SeoAnalysisRequest(
        product_url="https://brand.naver.com/vayapet/products/9864738770",
        keyword="방울양배추",
        cached_rank=5,
        cached_product_name="방울양배추 동결건조 강아지 간식",
        cached_competitors=[{
            "rank": 7,
            "product_id": "1111111111",
            "product_url": "https://brand.naver.com/vayapet/products/1111111111",
            "product_name": "동일 브랜드스토어 상품",
            "price": 12300,
            "brand": "바야",
            "store_name": "바야 프리미엄 펫푸드",
            "category1": "생활/건강",
            "category2": "반려동물",
        }],
        cached_total_volume=1000,
        cached_review_count=540,
        cached_rating=4.88,
    )

    result = seo_analyze(req, current_user={"id": 1})["data"]
    assert result["product_info"]["price"] == 12300
    assert result["product_info"]["category2"] == "반려동물"


def test_exact_product_id_wins_before_same_store_fallback():
    wrong = {
        "rank": 1,
        "product_id": "1111111111",
        "product_url": "https://smartstore.naver.com/vayapet/products/1111111111",
        "product_name": "같은 스토어의 다른 상품",
        "price": 9900,
        "brand": "바야",
        "store_name": "vayapet",
        "category1": "생활/건강",
        "category2": "반려동물",
    }
    exact = dict(
        wrong,
        rank=2,
        product_id="9864738770",
        product_url="https://search.shopping.naver.com/main/products/9864738770",
        product_name="신고 대상 정확 상품",
        price=12300,
        store_name="바야 프리미엄 펫푸드",
    )
    req = SeoAnalysisRequest(
        product_url="https://smartstore.naver.com/vayapet/products/9864738770",
        keyword="방울양배추",
        cached_rank=2,
        cached_competitors=[wrong, exact],
        cached_total_volume=1000,
        cached_review_count=540,
        cached_rating=4.88,
    )

    result = seo_analyze(req, current_user={"id": 1})["data"]
    assert result["product_info"]["product_name"] == "신고 대상 정확 상품"
    assert result["product_info"]["price"] == 12300


def test_cached_product_info_url_match_uses_exact_parsed_id_after_direct_id_miss():
    wrong = {
        "rank": 1,
        "product_id": "9123",
        "product_url": "https://search.shopping.naver.com/main/products/9123?next=/products/123",
        "product_name": "부분 문자열만 겹친 다른 상품",
        "price": 9900,
        "brand": "다른 브랜드",
        "store_name": "다른 판매처",
        "category1": "생활/건강",
        "category2": "반려동물",
    }
    exact_url = dict(
        wrong,
        rank=2,
        product_id="",
        product_url="https://search.shopping.naver.com/catalog/123",
        product_name="경로에서 정확히 추출한 상품",
        price=12300,
        brand="바야",
        store_name="바야 프리미엄 펫푸드",
    )
    req = SeoAnalysisRequest(
        product_url="https://brand.naver.com/vayapet/products/123",
        keyword="방울양배추",
        cached_rank=2,
        cached_product_info={"product_name": ""},
        cached_competitors=[wrong, exact_url],
        cached_total_volume=1000,
    )

    result = seo_analyze(req, current_user={"id": 1})["data"]
    assert result["product_info"]["product_name"] == "경로에서 정확히 추출한 상품"
    assert result["product_info"]["price"] == 12300


def test_detail_page_api_exposes_captured_brand_product_name():
    html = r'''
        <html><body><div class="product-detail">상품 상세</div><script>
        window.__PRELOADED_STATE__={
          "simpleProductForDetailPage":{
            "id":9864738770,
            "name":"캡처에서 확보한 브랜드 상품명",
            "salePrice":12300,
            "reviewAmount":{"totalReviewCount":540,"averageReviewScore":4.88}
          }
        };
        </script></body></html>
    '''
    response = detail_page_analyze(
        DetailPageAnalysisRequest(
            html=html,
            product_url="https://brand.naver.com/vayapet/products/9864738770",
        ),
        current_user={"id": 1},
    )

    assert response["success"] is True
    assert response["data"]["productName"] == "캡처에서 확보한 브랜드 상품명"


def test_captured_measurements_with_empty_search_are_neutral_and_do_not_recrawl():
    """성공적인 0건 검색은 재수집 대상이 아니며, 경쟁상품 없음은 실측값 실패가 아니다."""
    original_crawl = main_module._shared_crawl
    main_module._shared_crawl = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("cached_rank=0에서는 순위를 다시 수집하면 안 된다")
    )
    try:
        response = seo_analyze(
            SeoAnalysisRequest(
                product_url="https://brand.naver.com/vayapet/products/9864738770",
                keyword="방울양배추",
                cached_rank=0,
                cached_product_name="og 폴백 상품명",
                cached_product_info={
                    "product_name": "PRELOADED 실제 상품명",
                    "price": 12300,
                    "category1": "생활/건강",
                    "category2": "반려동물",
                    "store_name": "바야 프리미엄 펫푸드",
                },
                cached_competitors=[],
                cached_total_volume=1000,
                cached_review_count=540,
                cached_rating=4.88,
            ),
            current_user={"id": 1},
        )["data"]
    finally:
        main_module._shared_crawl = original_crawl

    assert response["product_info"]["product_name"] == "PRELOADED 실제 상품명"
    assert response["scores"]["price"] == 50
    assert response["scores"]["category"] == 50
    assert response["data_quality"]["review_count"]["status"] == "measured"
    assert response["data_quality"]["review_count"]["sources"] == ["html_capture"]
    assert response["data_quality"]["rating"]["status"] == "measured"
    assert response["data_quality"]["rating"]["sources"] == ["html_capture"]
    assert response["data_quality"]["price"]["sources"] == ["cached_product_info"]


def test_nonempty_top_results_without_target_still_run_deep_rank_search():
    """80건 비교군에 대상이 없으면 cached_rank=0으로 닫지 않고 500위 경로를 탄다."""
    calls = []
    deep_target = {
        "rank": 137,
        "product_id": "9864738770",
        "product_url": "https://search.shopping.naver.com/catalog/9864738770",
        "product_name": "심층 검색에서 발견한 신고 상품",
        "price": 12300,
        "brand": "바야",
        "store_name": "바야 프리미엄 펫푸드",
        "category1": "생활/건강",
        "category2": "반려동물",
    }
    original_crawl = main_module._shared_crawl
    main_module._shared_crawl = lambda keyword, limit: (
        calls.append((keyword, limit)) or [deep_target]
    )
    try:
        response = seo_analyze(
            SeoAnalysisRequest(
                product_url="https://brand.naver.com/vayapet/products/9864738770",
                keyword="방울양배추",
                cached_product_info={
                    "product_name": "신고 대상 상품",
                    "price": 12300,
                    "brand": "바야",
                    "store_name": "바야 프리미엄 펫푸드",
                    "category1": "생활/건강",
                    "category2": "반려동물",
                },
                cached_competitors=[{
                    "rank": index + 1,
                    "product_id": str(5000000000 + index),
                    "product_url": (
                        "https://search.shopping.naver.com/catalog/"
                        f"{5000000000 + index}"
                    ),
                    "product_name": f"80건 안의 다른 상품 {index + 1}",
                    "price": 9900 + index,
                } for index in range(80)],
                cached_total_volume=1000,
                cached_review_count=540,
                cached_rating=4.88,
            ),
            current_user={"id": 1},
        )["data"]
    finally:
        main_module._shared_crawl = original_crawl

    assert calls == [("방울양배추", 500)]
    assert response["scores"]["detail"]["current_rank"] == 137


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
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
