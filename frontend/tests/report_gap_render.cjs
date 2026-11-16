/* 보고서 빈칸 문구 고침(2026-11-16) — 실제 번들을 헤드리스 크롬에 올려 「자료 없음 / 자료 있음」 두 경우를 그려 보는 로컬 확인.
 * 배포 게이트에는 넣지 않았다(러너에 크롬이 없다). 실행: node frontend/build.js 뒤
 *   node frontend/tests/report_gap_render.cjs <frontend 경로> <react@18.2.0 · react-dom@18.2.0 이 깔린 폴더>
 * 네트워크 0 — CDN·/api 요청을 모두 가로채 가짜로 답한다. */
// 보고서 빈칸 문구 고침 — 실제 번들을 헤드리스 크롬에 올려 두 경우(자료 없음 / 자료 있음)를 그려 본다.
// 화면 글자와 내보내기(ReportCapture.buildHtml) 결과를 함께 확인한다. 네트워크 0(CDN·API 모두 가로챔).
const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const FE = process.argv[2];
const RX = process.argv[3];
const results = [];
function check(name, ok, extra) { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + (extra || ''))); }

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/index.bundle.html';
  const f = path.join(FE, p);
  if (!f.startsWith(FE) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
  const ext = path.extname(f);
  res.writeHead(200, { 'Content-Type': ext === '.js' ? 'application/javascript' : ext === '.css' ? 'text/css' : 'text/html; charset=utf-8' });
  fs.createReadStream(f).pipe(res);
});

function scenario(noMarket) {
  const vol = { relKeyword: '예시키워드', monthlyPcQcCnt: 4050, monthlyMobileQcCnt: 10000, monthlyAvePcClkCnt: 30, monthlyAveMobileClkCnt: 80, plAvgDepth: 15, compIdx: '높음' };
  const advertiserReport = noMarket ? {
    market_data_available: false,
    product_info: { product_name: '[예시] 바삭한 수제 부각 120g', price: 12900, store_name: '예시상점' },
    ranking: { current_rank: null },
    competitor_comparison: { items: [], stats: {} },
    entry_strategy: { overall_score: null, strategies: [
      { area: '가격 전략', severity: 'medium', insights: ['현재 판매가는 12,900원입니다. 경쟁 상품 가격 자료가 없어 가격 비교는 넣지 않았습니다.'], actions: [] },
    ] },
  } : {
    market_data_available: true,
    product_info: { product_name: '[예시] 바삭한 수제 부각 120g', price: 12900, store_name: '예시상점' },
    ranking: { current_rank: 12 },
    competitor_comparison: { items: [], stats: { avg_price: 15000, min_price: 9000, max_price: 30000, keyword_in_name_ratio: 70 } },
    entry_strategy: { overall_score: 62, strategies: [{ area: '가격 전략', severity: 'high', insights: ['1페이지 평균가는 15,000원입니다.'], actions: [] }] },
  };
  return {
    advertiserLoading: false, advertiserReport,
    analysisData: {
      marketMissing: noMarket,
      summaryCards: { totalVolume: '14,050', productCount: noMarket ? '0' : '3,200', goldenCount: 3, compLevel: noMarket ? '-' : '보통', relatedLookupFailed: false },
      advertiserInfo: { adDepth: 15, pcClicks: '30.0', mobileClicks: '80.0', compIdx: '높음' },
      goldenKeyword: { name: '예시 골든', score: 70, volume: 3000, competition: '낮음', ctr: 2.1, clicks: 150, reason: '예시' },
    },
    companyName: '', currentUser: { role: 'manager', name: '테스트' },
    datalabData: noMarket ? { categoryDefaulted: true } : null, datalabLoading: false,
    auditStatus: { phase: 'collected', items: [{ name: '검색량', st: 'ok' }, { name: '연관 키워드', st: 'ok' }, { name: '상품 검색', st: noMarket ? 'off' : 'ok' }] },
    handleNavigateToClient: function () {}, htmlDetailResult: null, htmlReviewData: null,
    lastHtmlRef: { current: '' }, loadProducts: function () {}, products: [], rankCheckResult: null,
    relatedData: { related_keywords: [{ keyword: '예시 연관', totalVolume: 1000 }], golden_keywords: [], total_found: 1, lookup_ok: true },
    scrollTo: function () {}, searchLoading: false, searchedKeyword: '예시키워드',
    searchedProductUrl: 'https://smartstore.naver.com/example/products/123', sections: [],
    setRankCheckResult: function () {}, shopProducts: [],
    volumeData: noMarket ? [] : [vol],
  };
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  let exposureMeasured = 0;
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.includes('cdnjs.cloudflare.com/ajax/libs/react/')) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(RX, 'node_modules/react/umd/react.production.min.js')) });
    if (u.includes('cdnjs.cloudflare.com/ajax/libs/react-dom/')) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(RX, 'node_modules/react-dom/umd/react-dom.production.min.js')) });
    if (u.includes('/api/rank/keyword-exposure')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true, data: { total_keywords: 3, exposed_count: 0, measured_count: exposureMeasured, results: [
      { keyword: '예시키워드', rank: null, source: 'own', measured: exposureMeasured > 0 }, { keyword: '수제 부각', rank: null, source: 'own', measured: false }, { keyword: '부각', rank: null, source: 'own', measured: false }], recommended: [] } }) });
    if (u.includes('/api/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: false }) });
    if (u.startsWith('http://127.0.0.1:' + port)) return route.continue();
    return route.fulfill({ status: 404, body: '' });
  });
  await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => !!window.AnalysisResults && !!window.ReportCapture);

  for (const noMarket of [true, false]) {
    exposureMeasured = noMarket ? 0 : 3;
    const tag = noMarket ? '[자료 없음] ' : '[자료 있음] ';
    const props = JSON.parse(JSON.stringify(scenario(noMarket)));
    await page.evaluate((p) => {
      document.querySelectorAll('#harness').forEach(n => n.remove());
      const host = document.createElement('div'); host.id = 'harness'; document.body.appendChild(host);
      // 함수 칸 되살리기
      p.handleNavigateToClient = p.loadProducts = p.scrollTo = p.setRankCheckResult = function () {};
      window.__root && window.__root.unmount();
      window.__root = ReactDOM.createRoot(host);
      window.__root.render(React.createElement(window.AnalysisResults, p));
    }, props);
    await page.waitForTimeout(1500);
    const txt = await page.evaluate(() => document.getElementById('harness').innerText);
    const html = await page.evaluate(() => {
      // ReportCapture 는 .report-main 을 복제한다 — 하네스 안의 것을 쓰도록 바깥 앱의 것은 잠깐 뗀다.
      const outer = document.querySelector('#root .report-main');
      const parent = outer && outer.parentNode; const next = outer && outer.nextSibling;
      if (outer) outer.remove();
      let h = '';
      try { h = window.ReportCapture.buildHtml({ title: '시험' }); } finally { if (outer) parent.insertBefore(outer, next); }
      return h;
    });
    const exp = html.replace(/<style[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    if (noMarket) {
      check(tag + '화면 안내 띠(이유 포함)', txt.includes('쇼핑 시장 자료 없음') && txt.includes('2026-11-05') && txt.includes('고장이 아닙니다'));
      check(tag + '검수 줄 「상품 검색 · 수집 쉬는 중」', txt.includes('상품 검색 · 수집 쉬는 중') && !txt.includes('✗ 상품 검색'));
      check(tag + '종합 점수 「계산 불가」', txt.includes('종합 진입 점수 · 계산 불가'));
      check(tag + '「등록 상품수」 자료 없음', /등록 상품수\s*자료 없음/.test(txt));
      check(tag + '장마다 「이번 분석에서 빠진 칸」', (txt.match(/이번 분석에서 빠진 칸/g) || []).length === 4, (txt.match(/이번 분석에서 빠진 칸/g) || []).length);
      check(tag + '「미노출」 없음', !txt.includes('미노출'));
      check(tag + '현재 순위 · 못 잼', txt.includes('현재 순위 · 못 잼'));
      check(tag + '경쟁 비교표 대신 한 줄', txt.includes('상위 10개 비교표와 격차 분석을 만들지 않았습니다') && !txt.includes('경쟁사 상위 10개 비교표'));
      check(tag + '예상 CPC 「0」 대신 안내', txt.includes('예상 CPC를 계산하지 못했습니다'));
      check(tag + '데이터랩 「생활/건강」 기준 안내', txt.includes('「생활/건강」 기준'));
      check(tag + '노출 순위 「못 잼」(200위 밖 아님)', txt.includes('키워드별 순위 · 못 잼') && !txt.includes('200위 밖 키워드'));
      check(tag + '전달본 맨 위 한 줄', exp.includes('검색 수요 · 키워드 · 광고 경쟁 자료를 중심으로 작성했습니다'));
      check(tag + '전달본에 내부 사정·직원 안내 없음', !exp.includes('쇼핑 순위 수집을') && !exp.includes('이번 분석에서 빠진 칸') && !exp.includes('계산 불가') && !exp.includes('못 잼') && !exp.includes('데이터 검수'));
      check(tag + '전달본에 「등록 상품수」·「경쟁강도」 칸 없음', !exp.includes('등록 상품수') && !/경쟁강도\s+(자료 없음|—)/.test(exp));
      check(tag + '전달본 목차에 빈 「3. 경쟁 진단」 남지 않으면 됨(광고 경쟁 칸이 있어 장 유지)', exp.includes('3. 경쟁 진단') && exp.includes('광고'));
      check(tag + '전달본에 「0원」·「0%」 없음', !/\b0원/.test(exp) && !/ 0%/.test(exp));
    } else {
      check(tag + '안내 띠·빠진 칸 줄 없음(종전과 같음)', !txt.includes('쇼핑 시장 자료 없음') && !txt.includes('이번 분석에서 빠진 칸'));
      check(tag + '종합 점수 그대로', txt.includes('종합 진입 점수') && !txt.includes('계산 불가'));
      check(tag + '현재 순위 12위', txt.includes('12위'));
      check(tag + '경쟁사 상위 10개 비교표 그대로', txt.includes('경쟁사 상위 10개 비교표'));
      check(tag + '예상 CPC 칸 나옴', !txt.includes('예상 CPC를 계산하지 못했습니다'));
      check(tag + '노출 순위 실측 표시', txt.includes('200위 밖 키워드') && !txt.includes('키워드별 순위 · 못 잼'));
      check(tag + '전달본에 맨 위 한 줄 없음', !exp.includes('중심으로 작성했습니다'));
      check(tag + '전달본에 「등록 상품수」 있음', exp.includes('등록 상품수'));
    }
  }
  check('페이지 오류 0', errs.length === 0, errs.join(' | ').slice(0, 300));
  await browser.close(); server.close();
  const failed = results.filter(r => !r.ok).length;
  console.log('\n결과: ' + (results.length - failed) + ' 통과 · ' + failed + ' 실패');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
