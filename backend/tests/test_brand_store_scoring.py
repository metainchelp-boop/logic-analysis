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


from main import SeoAnalysisRequest, seo_analyze  # noqa: E402


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
    mobile = _analyze("https://m.brand.naver.com/vayapet/products/9864738770")
    detail = mobile["scores"]["detail"]

    assert detail["is_naver_store"] is True
    assert detail["is_smartstore"] is False
    assert detail["has_naverpay"] is True


def test_mobile_smartstore_keeps_its_existing_platform_and_legacy_flags():
    mobile = _analyze("https://m.smartstore.naver.com/vayapet/products/9864738770")
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
