"""보고서 빈칸 문구 고침(2026-11-16 · 대표 결정 「보고서 문구 — ①ⓐ ②ⓐ ③ⓐ」) 회귀.

쇼핑 순위 수집을 쉰 뒤(2026-11-05~) 쇼핑 1페이지 자료가 없을 때
  ① 광고주 전달본은 빈 칸·빈 장을 빼고 맨 위에 한 줄만
  ② 종합 진입 점수는 「계산 불가」(시작값 50 을 내지 않음)
  ③ 직원 화면은 이유까지 적은 안내
를 지키는지 본다. 자료가 있으면 종전과 같아야 한다(무회귀).

외부 네트워크 0 · DB 0. 서버 전체 의존성(apscheduler 등)이 깔린 곳에서는 compute_advertiser_report 를
실제로 불러 확인하고, 없는 곳(배포 회귀 게이트)에서는 그 부분만 건너뛰고 소스·자동 보고서로 확인한다.
"""
import os
import re
import sys
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FE = ROOT / "frontend" / "js"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("JWT_SECRET_KEY", "offline-report-gap-test-only")

# 외부 연결 금지 — 실수로 네이버에 묻는 시험이 되지 않게
_real_connect = socket.socket.connect
def _no_net(self, addr):
    raise AssertionError(f"외부 연결 금지: {addr}")
socket.socket.connect = _no_net

passed = failed = skipped = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {extra}")

def read(p):
    return Path(p).read_text(encoding="utf-8")

# ── 1) 08:30 자동 보고서(generate_html_report) — 실제 함수 ──────────────────────────
import auto_analysis as aa

def body_text(html):
    html = re.sub(r"<style[\s\S]*?</style>", "", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

no_mkt = aa.generate_html_report("예시키워드", "예시업체", {
    "summaryCards": {"totalVolume": "14,050", "productCount": "0", "goldenCount": 3, "compLevel": "-"},
})
t = body_text(no_mkt)
check("자동 보고서 · 자료 없음 → 맨 위 한 줄", "검색 수요 · 키워드 · 광고 경쟁" in t and "담지 않았습니다" in t)
check("자동 보고서 · 자료 없음 → 「상품 수 0」 칸 없음", "상품 수" not in t)
check("자동 보고서 · 자료 없음 → 「경쟁강도 -」 칸 없음", "경쟁강도" not in t)
check("자동 보고서 · 자료 없음 → 검색량 칸은 그대로", "월간 검색량" in t and "14,050" in t)
check("자동 보고서 · 내부 사정(수집 쉼)을 적지 않음", "수집" not in t)

with_mkt = aa.generate_html_report("예시키워드", "예시업체", {
    "summaryCards": {"totalVolume": "14,050", "productCount": "3,200", "goldenCount": 3, "compLevel": "보통"},
})
t2 = body_text(with_mkt)
check("자동 보고서 · 자료 있음 → 맨 위 한 줄 없음(종전과 같음)", "담지 않았습니다" not in t2)
check("자동 보고서 · 자료 있음 → 상품 수·경쟁강도 칸 그대로", "상품 수" in t2 and "3,200" in t2 and "경쟁강도" in t2 and "보통" in t2)

# ── 2) 서버 문장(compute_advertiser_report) — 소스 고정 ──────────────────────────────
src = read(BACKEND / "main.py")
fn = src[src.index("def compute_advertiser_report"):]
fn = fn[:fn.index("\n@app.")]
check("서버 · 시장 자료 판정 한 곳(market_ok)", "market_ok = bool(page1_products)" in fn)
check("서버 · 자료 없으면 점수 None(계산 불가)", re.search(r"if not market_ok:(?:\s*#[^\n]*\n)*\s*score = None", fn) is not None)
check("서버 · 응답에 market_data_available", '"market_data_available": market_ok' in fn)
check("서버 · 가격 문장 「가격 비교는 넣지 않았습니다」", "가격 비교는 넣지 않았습니다" in fn)
check("서버 · 카테고리 문장 「카테고리 점유율은 넣지 않았습니다」", "카테고리 점유율은 넣지 않았습니다" in fn)
check("서버 · 순위 문장 「순위 기반 조언은 넣지 않았습니다」", "순위 기반 조언은 넣지 않았습니다" in fn)
rel = src[src.index('"/api/keywords/related"'):]
rel = rel[:rel.index("\n@app.")]
check("서버 · 연관 키워드 응답에 lookup_ok(조회 실패 ≠ 0개)", '"lookup_ok": lookup_ok' in rel and "lookup_ok = True" in rel)
# 띄어 쓴 키워드 — keywordstool 은 hintKeywords 에 공백이 있으면 400(naver_crawler 와 같은 규칙).
# 원문을 그대로 보내면 「수제 부각」 같은 키워드는 연관 키워드가 늘 「불러오지 못함」이 된다(2026-11-16 운영 실측 400 6건).
check("서버 · 연관 키워드 조회는 공백을 뺀 키워드로 묻는다",
      '"hintKeywords": (req.keyword or "").strip().replace(" ", "")' in rel
      and '"hintKeywords": req.keyword,' not in rel)
exp = src[src.index('"/api/rank/keyword-exposure"'):]
exp = exp[:exp.index("\n@app.")]
check("서버 · 노출 순위에 measured · measured_count(못 잼 ≠ 200위 밖)", '"measured": bool(_prods)' in exp and '"measured_count"' in exp)
fb = src[src.index('"/api/ai/feedback-all"'):]
fb = fb[:fb.index("\n@app.")]
check("서버 · AI 에 「경쟁 상품 자료 없음」 일러 둠", 'req.sections.get("marketMissing")' in fb and "0으로 단정하지 말고" in fb)

# 실제 실행(서버 전체 의존성이 있을 때만)
try:
    import apscheduler  # noqa: F401
    have_full = True
except Exception:
    have_full = False
if have_full:
    import tempfile
    os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp()) / "t.db"))
    import main
    import naver_crawler
    info = {"product_name": "[예시] 바삭한 수제 부각 120g", "price": 12900, "store_name": "예시상점", "category": ""}
    orig = (main.get_product_info, main._shared_crawl, main.find_product_rank, naver_crawler.search_products)
    main.get_product_info = lambda *a, **k: dict(info)
    naver_crawler.search_products = lambda *a, **k: []
    main.find_product_rank = lambda *a, **k: (None, None, [])
    try:
        main._shared_crawl = lambda *a, **k: []
        r = main.compute_advertiser_report("예시키워드", "https://smartstore.naver.com/example/products/123")
        d = r.get("data") if isinstance(r, dict) and "data" in r else r
        es = d.get("entry_strategy", {})
        alltext = " ".join(" ".join(s.get("insights", []) + s.get("actions", [])) for s in es.get("strategies", []))
        check("실행 · 자료 없음 → market_data_available False", d.get("market_data_available") is False)
        check("실행 · 자료 없음 → 점수 None", es.get("overall_score") is None, es.get("overall_score"))
        # 「12,900원」 안의 「0원」은 세지 않는다 — 앞이 숫자·쉼표가 아닌 0원만
        check("실행 · 자료 없음 → 「0원」 문장 없음", re.search(r"(?<![\d,])0원", alltext) is None and "0~0원" not in alltext, alltext[:200])
        check("실행 · 자료 없음 → 「점유율 0%」 없음", "점유율 0%" not in alltext)
        check("실행 · 자료 없음 → 「노출되지 않고 있습니다」 없음", "노출되지 않고 있습니다" not in alltext)
        check("실행 · 자료 없음 → 내 판매가는 그대로 적음", "12,900원" in alltext)
        # 순위를 못 잰 것으로 「긴급」을 고르지 않는다(상품명에 키워드가 없는 것처럼 내 상품 기준 판정은 그대로)
        comp = [s for s in es.get("strategies", []) if s.get("area") == "경쟁 환경 & 차별화 방향"]
        check("실행 · 자료 없음 → 순위 못 잼으로 「긴급(high)」 고르지 않음", bool(comp) and comp[0].get("severity") != "high",
              [s.get("severity") for s in comp])
        # 자료 있음 — 종전과 같은 모양(점수 숫자 · 평균가 문장)
        fake = [{"rank": i + 1, "product_name": f"예시 상품 {i}", "price": 10000 + i * 100, "store_name": f"s{i}",
                 "category1": "식품", "category2": "과자", "category3": "", "review_count": 10, "product_url": f"https://x/{i}",
                 "product_id": str(i), "brand": ""} for i in range(40)]
        main._shared_crawl = lambda *a, **k: list(fake)
        r2 = main.compute_advertiser_report("예시키워드", "https://smartstore.naver.com/example/products/123")
        d2 = r2.get("data") if isinstance(r2, dict) and "data" in r2 else r2
        es2 = d2.get("entry_strategy", {})
        check("실행 · 자료 있음 → market_data_available True", d2.get("market_data_available") is True)
        check("실행 · 자료 있음 → 점수 숫자(종전과 같음)", isinstance(es2.get("overall_score"), (int, float)), es2.get("overall_score"))
        t3 = " ".join(" ".join(s.get("insights", [])) for s in es2.get("strategies", []))
        check("실행 · 자료 있음 → 경쟁 평균가 문장 그대로", "경쟁 평균(11,950원)" in t3, t3[:200])
        comp2 = [s for s in es2.get("strategies", []) if s.get("area") == "경쟁 환경 & 차별화 방향"]
        check("실행 · 자료 있음 → 순위 미노출은 종전처럼 high", bool(comp2) and comp2[0].get("severity") == "high",
              [s.get("severity") for s in comp2])
    finally:
        main.get_product_info, main._shared_crawl, main.find_product_rank, naver_crawler.search_products = orig
    # 연관 키워드 — 실제 함수가 검색광고에 보내는 hintKeywords(네트워크는 가로챔)
    import requests as _rq
    sent = []
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"keywordList": []}
    _orig_get = _rq.get
    _orig_keys = (naver_crawler.SEARCHAD_API_KEY, naver_crawler.SEARCHAD_SECRET_KEY, naver_crawler.SEARCHAD_CUSTOMER_ID)
    try:
        naver_crawler.SEARCHAD_API_KEY, naver_crawler.SEARCHAD_SECRET_KEY, naver_crawler.SEARCHAD_CUSTOMER_ID = "k", "s", "c"
        _rq.get = lambda url, params=None, **k: (sent.append(dict(params or {})), _Resp())[1]
        out = main.related_keywords(main.RelatedKeywordRequest(keyword=" 수제 부각 "), current_user={"id": 1})
        hk = [p.get("hintKeywords") for p in sent if "hintKeywords" in p]
        check("실행 · 띄어 쓴 키워드 → 검색광고에 공백 없이 보냄", bool(hk) and hk[0] == "수제부각", hk)
        d3 = out.get("data") if isinstance(out, dict) else None
        check("실행 · 조회 성공이면 lookup_ok True", isinstance(d3, dict) and d3.get("lookup_ok") is True,
              (d3 or {}).get("lookup_ok") if isinstance(d3, dict) else out)
    finally:
        _rq.get = _orig_get
        naver_crawler.SEARCHAD_API_KEY, naver_crawler.SEARCHAD_SECRET_KEY, naver_crawler.SEARCHAD_CUSTOMER_ID = _orig_keys
else:
    skipped += 1
    print("  SKIP  실행 확인(서버 전체 의존성 없음 — 소스 고정으로 갈음)")

# ── 3) 화면 소스 고정 ─────────────────────────────────────────────────────────────
ar = read(FE / "components" / "AnalysisResults.jsx")
check("화면 · 예상 CPC 「0」 결함 — `volumeData.length &&` 조건이 다시 생기지 않음",
      re.search(r"volumeData\s*&&\s*volumeData\.length\s*&&", ar) is None)
check("화면 · 직원 안내 띠는 no-export · 이유(2026-11-05) 포함", "쇼핑 시장 자료 없음" in ar and "2026-11-05" in ar and "고장이 아닙니다" in ar)
check("화면 · 전달본 한 줄은 export-only(화면에서는 숨김)", "export-only" in ar and "중심으로 작성했습니다" in ar)
check("화면 · 데이터 검수 줄은 전달본에서 뺌", "'section fade-in no-export'" in ar)
rc = read(FE / "report-capture.js")
check("내보내기 · export-only 를 보이게 함", ".export-only" in rc and "classList.remove('export-only')" in rc)
check("내보내기 · 빈 장 빼기(dropEmptyChapters) 가 목차보다 먼저", "function dropEmptyChapters" in rc
      and rc.index("dropEmptyChapters(clone)") < rc.index("insertToc(clone);", rc.index("function buildHtml")))
an = read(FE / "analysis.jsx")
check("분석 · 「성공 · 빈 목록」 상품 검색은 다시 묻지 않음(off)",
      "var shopOff = !ok.shop && _shopOff(results[2]);" in an
      and "(!ok.shop && !shopOff)" in an
      and "_auditItems['상품 검색'] = ok.shop ? 'ok' : (shopOff ? 'off'" in an)
check("분석 · 연관 키워드 lookup_ok=false 는 실패로 봄", "lookup_ok === false" in an)

socket.socket.connect = _real_connect
print(f"\n결과: {passed} 통과 · {failed} 실패 · {skipped} 건너뜀")
sys.exit(1 if failed else 0)
