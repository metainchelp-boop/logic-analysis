"""회귀 — 상세 HTML 의 검색엔진용 상품 정보(JSON-LD Product)로 판매가·카테고리·상품 주소 (대표 결정 A · 2026-09-23)

지키는 것:
  ① detail_ld — 판매가(offers.price → lowPrice · 쉼표·글자 숫자 · 100원~1억 밖이면 0) · 카테고리('>' 이름만) ·
     상품 번호(productID → sku · 숫자만) · 깨진 JSON·다른 @type·@graph·목록 형태에도 예외 없음.
  ② product_url — offers.url → 본문 같은 번호 주소 → 스토어 한 종류일 때만 조립 · 여러 스토어면 비운다 · \\/ 이스케이프 복원.
  ③ analyze_detail_page — 종전 자리(__NEXT_DATA__·api-price)가 비었을 때만 JSON-LD 로 채운다 ·
     종전 값이 있으면 그대로 · data_quality 출처가 html_json_ld 로 붙는다 · 이상탐지(범위) 그대로.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests as _rq  # noqa: E402


def _no_net(*a, **k):
    raise RuntimeError("network disabled in tests")


_rq.get = _no_net
_rq.post = _no_net

import detail_ld as dl  # noqa: E402
import naver_crawler as nc  # noqa: E402

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def ld_html(prod, body="", head=""):
    return ("<!DOCTYPE html><html><head>" + head + "</head><body>"
            '<script type="application/ld+json">' + json.dumps(prod, ensure_ascii=False) + "</script>"
            + body + '<div class="product-detail"><h1>x</h1></div></body></html>')


P = {"@context": "https://schema.org", "@type": "Product", "name": "시험상품", "productID": "1234567",
     "sku": "1234567", "mpn": "1234567", "category": "식품 > 과자/베이커리 > 쿠키",
     "offers": {"@type": "Offer", "price": "12900", "priceCurrency": "KRW",
                "url": "https://smartstore.naver.com/teststore/products/1234567"}}

print("① detail_ld 판독")
prod = dl.product_ld(ld_html(P))
ok("🔴 JSON-LD Product 를 찾는다", isinstance(prod, dict) and prod.get("productID") == "1234567")
ok("🔴 판매가 = offers.price(글자 숫자)", dl.price(prod) == 12900)
ok("쉼표 섞인 판매가", dl.price({"offers": {"price": "1,290,000"}}) == 1290000)
ok("숫자형 판매가 · lowPrice 폴백", dl.price({"offers": {"price": 5500}}) == 5500
   and dl.price({"offers": {"lowPrice": "7000"}}) == 7000)
ok("offers 가 목록이어도 첫 값", dl.price({"offers": [{"price": "8800"}]}) == 8800)
ok("🔴 100원 미만·1억 초과는 버린다(0)", dl.price({"offers": {"price": "50"}}) == 0
   and dl.price({"offers": {"price": "999999999"}}) == 0)
ok("못 읽는 값은 0", dl.price({"offers": {"price": "문의"}}) == 0 and dl.price({}) == 0 and dl.price(None) == 0)
ok("🔴 카테고리 — 공백 정리 · 대분류", dl.category(prod) == ("식품>과자/베이커리>쿠키", "식품"), str(dl.category(prod)))
ok("카테고리가 숫자 코드뿐이면 비운다", dl.category({"category": "50000149"}) == ("", ""))
ok("카테고리가 목록이면 '>' 로 잇는다", dl.category({"category": ["식품", "과자"]}) == ("식품>과자", "식품"))
ok("🔴 상품 번호 — productID → sku · 숫자만", dl.product_no(prod) == "1234567"
   and dl.product_no({"sku": "7654321"}) == "7654321" and dl.product_no({"productID": "abc"}) == "")
ok("다른 @type 은 무시 · @graph 안의 Product 는 찾는다",
   dl.product_ld(ld_html({"@type": "BreadcrumbList"})) is None
   and (dl.product_ld(ld_html({"@graph": [{"@type": "WebPage"}, P]})) or {}).get("productID") == "1234567")
ok("깨진 JSON·빈 입력·글자 아님에도 예외 없음",
   dl.product_ld('<script type="application/ld+json">{깨짐</script>') is None
   and dl.product_ld("") is None and dl.product_ld(None) is None and dl.product_url(None) == "")

print("\n② product_url 조립")
ok("🔴 offers.url 이 상품 주소면 그대로", dl.product_url(ld_html(P)) == "https://smartstore.naver.com/teststore/products/1234567")
P2 = dict(P); P2["offers"] = {"price": "12900"}
body_same = '<a href="https://smartstore.naver.com/teststore/products/1234567?NaPm=x">본상품</a>' \
            '<a href="https://smartstore.naver.com/teststore/products/999">다른상품</a>'
ok("🔴 offers.url 없으면 본문에서 같은 번호 주소", dl.product_url(ld_html(P2, body_same)) == "https://smartstore.naver.com/teststore/products/1234567")
body_slug = '<a href="https://smartstore.naver.com/teststore">스토어</a><a href="https://smartstore.naver.com/teststore/products/999">x</a>'
ok("🔴 같은 번호 주소가 없어도 스토어가 한 종류면 조립", dl.product_url(ld_html(P2, body_slug)) == "https://smartstore.naver.com/teststore/products/1234567")
body_two = '<a href="https://smartstore.naver.com/storea">a</a><a href="https://smartstore.naver.com/storeb">b</a>'
ok("🔴 스토어가 두 종류면 조립하지 않는다(남의 스토어 오인 방지)", dl.product_url(ld_html(P2, body_two)) == "")
body_esc = '<script>var s="https:\\/\\/smartstore.naver.com\\/teststore\\/products\\/1234567";</script>'
ok("\\/ 이스케이프 안의 같은 번호 주소도 찾는다", dl.product_url(ld_html(P2, body_esc)) == "https://smartstore.naver.com/teststore/products/1234567")
body_brand = '<a href="https://brand.naver.com/brandx">b</a>'
ok("브랜드스토어도 조립", dl.product_url(ld_html(P2, body_brand)) == "https://brand.naver.com/brandx/products/1234567")
ok("main·inflow 같은 공용 경로는 스토어로 안 센다",
   dl.product_url(ld_html(P2, body_slug + '<a href="https://smartstore.naver.com/main/x">m</a><a href="https://smartstore.naver.com/inflow/y">i</a>')) == "https://smartstore.naver.com/teststore/products/1234567")
P3 = dict(P); P3["offers"] = {"price": "1", "url": "https://smartstore.naver.com/other/products/555"}
ok("offers.url 번호가 상품 번호와 다르면 그 주소를 믿지 않는다", dl.product_url(ld_html(P3, body_same)) == "https://smartstore.naver.com/teststore/products/1234567")
ok("JSON-LD 가 없으면 빈 값", dl.product_url("<html><body>" + body_slug + "</body></html>") == "")
# 실측(2026-09-23 · 746건 전부) — JSON-LD offers.url 은 스토어 이름 대신 main 이 든 범용 주소다.
PM = dict(P); PM["offers"] = {"price": "12900", "url": "https://smartstore.naver.com/main/products/1234567"}
ok("🔴 offers.url 이 /main/ 범용 주소뿐이면 쓰지 않는다(광고주 분석이 'main' 으로 엉뚱한 상품과 맞춘다)",
   dl.product_url(ld_html(PM)) == "" and dl.product_url_with_reason(ld_html(PM))[1] == "no-store")
ok("🔴 /main/ 범용 주소 + 진짜 스토어 한 종류 → 진짜 스토어로 조립",
   dl.product_url_with_reason(ld_html(PM, body_slug)) == ("https://smartstore.naver.com/teststore/products/1234567", "one-store"))
ok("같은 번호 주소가 진짜 스토어로 있으면 그것(여러 스토어가 섞여도)",
   dl.product_url_with_reason(ld_html(PM, body_two + '<a href="https://smartstore.naver.com/storeb/products/1234567">b</a>'))
   == ("https://smartstore.naver.com/storeb/products/1234567", "same-number"))
ok("사유 — 여러 스토어면 many-stores · JSON-LD 없으면 no-ld",
   dl.product_url_with_reason(ld_html(PM, body_two))[1] == "many-stores"
   and dl.product_url_with_reason("<html>" + body_slug + "</html>")[1] == "no-ld")

print("\n③ analyze_detail_page 배선")
rd = (nc.analyze_detail_page(ld_html(P), "") or {}).get("reviewData") or {}
ok("🔴 JSON-LD 만 있어도 판매가·카테고리가 채워진다", rd.get("price") == 12900 and rd.get("category") == "식품>과자/베이커리>쿠키"
   and rd.get("category1") == "식품", str({k: rd.get(k) for k in ("price", "category", "category1")}))
q = (rd.get("data_quality") or {}).get("price") or {}
ok("🔴 판매가 출처가 html_json_ld 로 붙는다", q.get("status") == "measured" and "html_json_ld" in (q.get("sources") or []), str(q))
nd = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
    {"props": {"pageProps": {"product": {"salePrice": 20000, "category": {"wholeCategoryName": "생활>세제"}}}}}) + "</script>"
rd2 = (nc.analyze_detail_page(ld_html(P, nd), "") or {}).get("reviewData") or {}
ok("🔴 종전 자리(__NEXT_DATA__)가 있으면 그 값이 먼저(무회귀)", rd2.get("price") == 20000 and rd2.get("category") == "생활>세제",
   str({k: rd2.get(k) for k in ("price", "category")}))
q2 = (rd2.get("data_quality") or {}).get("price") or {}
ok("종전 자리 값이면 출처도 종전(html_next_data)", "html_next_data" in (q2.get("sources") or []), str(q2))
rd3 = (nc.analyze_detail_page(ld_html(P, head='<meta name="api-price" content="15000">'), "") or {}).get("reviewData") or {}
ok("🔴 api-price 메타가 있으면 판매가는 그것 · 카테고리만 JSON-LD 로 채운다", rd3.get("price") == 15000 and rd3.get("category") == "식품>과자/베이커리>쿠키",
   str({k: rd3.get(k) for k in ("price", "category")}))
Pbad = dict(P); Pbad["offers"] = {"price": "999999999"}
rd4 = (nc.analyze_detail_page(ld_html(Pbad), "") or {}).get("reviewData") or {}
ok("범위 밖 JSON-LD 판매가는 미확인(None)", rd4.get("price") in (None, 0), str(rd4.get("price")))
rd5 = (nc.analyze_detail_page("<html><body><div class='product-detail'><h1>x</h1>" + "가" * 200 + "</div></body></html>", "") or {}).get("reviewData")
ok("JSON-LD 가 없는 HTML 은 종전 그대로(판매가 없음)", not rd5 or rd5.get("price") in (None, 0))

print("\n④ 화면(frontend/js/utils.js)의 같은 규칙과 답이 같다 — node 로 실제 함수를 돌려 대조")
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

node = shutil.which("node")
if not node:
    ok("node 가 있어야 이 검사를 돌린다(게이트는 setup-node 이후에 둔다)", False)
else:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    utils_src = open(os.path.join(root, "frontend", "js", "utils.js"), encoding="utf-8").read()
    s0 = utils_src.index("var _PRODUCT_NOT_SLUG")
    s1 = utils_src.index("// 저장용 상세분석 경량화")
    js_block = utils_src[utils_src.index("var _naverProductUrlRe"):s0] + utils_src[s0:s1]
    cases = [
        ld_html(P), ld_html(P2, body_same), ld_html(P2, body_slug), ld_html(P2, body_two), ld_html(P2, body_esc),
        ld_html(P2, body_brand), ld_html(P3, body_same), ld_html(PM), ld_html(PM, body_slug),
        ld_html(PM, body_two + '<a href="https://smartstore.naver.com/storeb/products/1234567">b</a>'),
        ld_html({"@graph": [{"@type": "WebPage"}, PM]}, body_slug), ld_html(dict(PM, productID="x", sku="7654321"), body_slug),
        "<html>" + body_slug + "</html>", '<script type="application/ld+json">{깨짐</script>' + body_slug,
    ]
    with tempfile.TemporaryDirectory() as td:
        cp = os.path.join(td, "cases.json")
        json.dump(cases, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
        jp = os.path.join(td, "run.js")
        open(jp, "w", encoding="utf-8").write(
            js_block + "\nconst cs = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));\n"
            "const h = s => s.indexOf('\\\\/') >= 0 ? s.replace(/\\\\\\//g, '/') : s;\n"
            "process.stdout.write(JSON.stringify(cs.map(c => [_productUrlFromLd(h(c)), extractProductUrlFromHtml(c)])));\n")
        out = subprocess.run([node, jp, cp], capture_output=True, text=True, timeout=30)
    try:
        js = json.loads(out.stdout)
    except Exception:
        js = None
    ok("utils.js 규칙이 node 에서 돈다", isinstance(js, list) and len(js) == len(cases), (out.stderr or "")[:300])
    if isinstance(js, list) and len(js) == len(cases):
        py = [dl.product_url(c) for c in cases]
        diff = [i for i, (a, b) in enumerate(zip(py, [x[0] for x in js])) if a != b]
        ok("🔴 JSON-LD 단계 — 서버(detail_ld)와 화면(utils.js)이 14사례 모두 같은 주소", not diff,
           str([(i, py[i], js[i][0]) for i in diff]))
        ok("🔴 화면 전체 규칙도 /main/ 범용 주소를 한 번도 돌려주지 않는다",
           not any("/main/" in (x[1] or "") for x in js), str([x[1] for x in js]))
        ok("화면 — /main/ 뿐인 JSON-LD 는 비우고, 진짜 스토어가 있으면 그 주소",
           js[7][1] == "" and js[8][1] == "https://smartstore.naver.com/teststore/products/1234567", str(js[7:9]))

print(f"\n결과: {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
