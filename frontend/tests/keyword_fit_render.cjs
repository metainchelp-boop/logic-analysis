/* 키워드 적합도 판정 「다시 받기」(2026-11-21) — 실제 번들을 헤드리스 크롬에 올려 보는 로컬 확인.
 * 배포 게이트에는 넣지 않았다(러너에 크롬이 없다 — 게이트에는 keyword-fit-key.test.cjs 가 같은 훅 코드를 돌린다).
 * 실행: node frontend/build.js 뒤
 *   node frontend/tests/keyword_fit_render.cjs <frontend 경로> <react@18.2.0 · react-dom@18.2.0 · playwright(-core) 가 깔린 폴더>
 *   이미 떠 있는 크롬에 붙으려면 CDP_URL=http://127.0.0.1:9333 을 준다(없으면 playwright 가 크롬을 띄운다).
 * 네트워크 0 — CDN·/api 요청을 모두 가로채 가짜로 답한다. 확인하는 것:
 *   판매자 태그 개수는 같고 내용만 바뀌어도 판정을 다시 받아 「상품명에 넣을 후보」가 바뀐다 · 같은 내용이면 다시 묻지 않는다 ·
 *   연관어 개수가 같은 다른 보고서로 갈아 끼워도 다시 묻는다 · 직원 화면의 제외 목록 개수 · 전달본에는 제외 목록이 없다. */
const http = require('http'), fs = require('fs'), path = require('path');
const FE = process.argv[2], RX = process.argv[3];
function need(name) { try { return require(name); } catch (e) { return require(path.join(RX, 'node_modules', name)); } }
let chromium; try { chromium = need('playwright').chromium; } catch (e) { chromium = need('playwright-core').chromium; }
const results = [];
function check(name, ok, extra) { results.push(!!ok); console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + (extra || ''))); }
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]); if (p === '/') p = '/index.bundle.html';
  const f = path.join(FE, p);
  if (!f.startsWith(FE) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
  const ext = path.extname(f);
  res.writeHead(200, { 'Content-Type': ext === '.js' ? 'application/javascript' : ext === '.css' ? 'text/css' : 'text/html; charset=utf-8' });
  fs.createReadStream(f).pipe(res);
});
function props(tags, related) {
  return {
    advertiserLoading: false,
    advertiserReport: { market_data_available: false, product_info: { product_name: '[예시] 프리미엄 생초콜릿 파베초콜릿', price: 18500, store_name: '예시상점' },
      ranking: { current_rank: null }, competitor_comparison: { items: [], stats: {} }, entry_strategy: { overall_score: null, strategies: [] } },
    analysisData: { marketMissing: true, summaryCards: { totalVolume: '9,510', productCount: '0', goldenCount: 1, compLevel: '-', relatedLookupFailed: false },
      advertiserInfo: { adDepth: 15, pcClicks: '30.0', mobileClicks: '80.0', compIdx: '중간' },
      goldenKeyword: { name: '수제초콜릿', score: 70, volume: 8860, competition: '낮음', ctr: 2.1, clicks: 150, reason: '예시' } },
    companyName: '', currentUser: { role: 'manager', name: '테스트' }, datalabData: null, datalabLoading: false,
    auditStatus: { phase: 'collected', items: [{ name: '검색량', st: 'ok' }, { name: '연관 키워드', st: 'ok' }] },
    htmlDetailResult: { sellerTags: tags, reviewData: { category: '식품>과자>초콜릿' } }, htmlReviewData: null,
    lastHtmlRef: { current: '' }, products: [], rankCheckResult: null,
    relatedData: { related_keywords: related.map((k, i) => ({ keyword: k, totalVolume: 9000 - i * 100, monthlyPcQcCnt: 100, monthlyMobileQcCnt: 200, compIdx: '중간' })), golden_keywords: [], total_found: related.length, lookup_ok: true },
    searchLoading: false, searchedKeyword: '파베초콜릿', searchedProductUrl: 'https://smartstore.naver.com/example/products/123', sections: [],
    shopProducts: [], volumeData: [{ relKeyword: '파베초콜릿', monthlyPcQcCnt: 1310, monthlyMobileQcCnt: 8200, monthlyAvePcClkCnt: 30, monthlyAveMobileClkCnt: 80, plAvgDepth: 15, compIdx: '중간' }],
  };
}
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const cdp = process.env.CDP_URL;
  const browser = cdp ? await chromium.connectOverCDP(cdp) : await chromium.launch();
  const context = (cdp && browser.contexts()[0]) || await browser.newContext();
  const page = await context.newPage();
  await page.setViewportSize({ width: 1280, height: 900 });
  const errs = []; page.on('pageerror', e => errs.push(String(e)));
  const fitCalls = [];
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.includes('cdnjs.cloudflare.com/ajax/libs/react/')) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(RX, 'node_modules/react/umd/react.production.min.js')) });
    if (u.includes('cdnjs.cloudflare.com/ajax/libs/react-dom/')) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(RX, 'node_modules/react-dom/umd/react-dom.production.min.js')) });
    if (u.includes('/api/keywords/fit')) {
      const b = JSON.parse(route.request().postData()).payload;
      const tags = (b.htmlDetail && b.htmlDetail.sellerTags) || [];
      fitCalls.push(tags.join(','));
      // 가짜 서버 — 판매자 태그에 있는 말만 통과시키고 나머지는 「같은 종류의 다른 상품」으로 뺀다
      const rows = b.related.related_keywords.map(r => r.keyword);
      const passed = rows.filter(k => tags.includes(k));
      const excluded = rows.filter(k => !tags.includes(k)).map(k => ({ keyword: k, total: 1000, reason: 'other_variety' }));
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true, data: {
        passed, targets: passed.map(k => ({ keyword: k, total: 1000, comp: '중간' })), nameCandidates: passed.map(k => ({ keyword: k, total: 1000 })),
        golden: [], excluded, excludedTotal: excluded.length + 100, reasons: { other_variety: '같은 종류의 다른 상품' }, gate: { version: 3, date: '2026-11-21', hasTags: true } } }) });
    }
    if (u.includes('/api/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: false }) });
    if (u.startsWith('http://127.0.0.1:' + port)) return route.continue();
    return route.fulfill({ status: 404, body: '' });
  });
  await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => !!window.AnalysisResults && !!window.ReportCapture);
  const mount = async (p) => { await page.evaluate((p) => {
      let host = document.getElementById('harness');
      if (!host) { host = document.createElement('div'); host.id = 'harness'; document.body.appendChild(host); window.__root = ReactDOM.createRoot(host); }
      p.handleNavigateToClient = p.loadProducts = p.scrollTo = p.setRankCheckResult = function () {};
      window.__root.render(React.createElement(window.AnalysisResults, p));   // 같은 root — 상태(받아 둔 판정)가 유지된다
    }, JSON.parse(JSON.stringify(p))); };
  const nameBox = () => page.evaluate(() => { const t = document.getElementById('harness').innerText; const i = t.indexOf('상품명에 넣을 후보'); return i < 0 ? '' : t.slice(i, i + 260).replace(/\s+/g, ' '); });
  const REL = ['다크초콜릿', '밀크초콜릿', '화이트초콜릿'];

  await mount(props(['다크초콜릿'], REL)); await page.waitForTimeout(1600);
  let box = await nameBox();
  check('첫 판정 — 한 번 묻고 후보는 다크초콜릿', fitCalls.length === 1 && box.includes('다크초콜릿') && !box.includes('밀크초콜릿'), JSON.stringify(fitCalls) + ' | ' + box);

  await mount(props(['다크초콜릿'], REL)); await page.waitForTimeout(1200);
  check('같은 내용으로 다시 그림 — 다시 묻지 않음', fitCalls.length === 1, JSON.stringify(fitCalls));

  await mount(props(['밀크초콜릿'], REL)); await page.waitForTimeout(1600);
  box = await nameBox();
  check('태그 개수는 같고 내용만 바뀜 — 다시 묻는다', fitCalls.length === 2 && fitCalls[1] === '밀크초콜릿', JSON.stringify(fitCalls));
  check('후보가 밀크초콜릿으로 바뀌고 다크초콜릿은 남지 않음', box.includes('밀크초콜릿') && !box.includes('다크초콜릿'), box);

  await mount(props(['밀크초콜릿'], ['말차초콜릿', '밀크초콜릿', '카카오닙스'])); await page.waitForTimeout(1600);
  check('연관어 개수는 같고 내용이 다른 보고서로 갈아 끼움 — 다시 묻는다', fitCalls.length === 3, JSON.stringify(fitCalls));

  const txt = await page.evaluate(() => document.getElementById('harness').innerText);
  check('직원 화면 — 제외 목록 전체 개수와 표시 개수', /제외된 키워드 102개 \(검색량 상위 2개만 표시\)/.test(txt.replace(/\s+/g, ' ')), (txt.match(/제외된 키워드[^\n]{0,60}/) || [''])[0]);
  const html = await page.evaluate(() => {
    const outer = document.querySelector('#root .report-main'); const parent = outer && outer.parentNode; const next = outer && outer.nextSibling;
    if (outer) outer.remove();
    let h = ''; try { h = window.ReportCapture.buildHtml({ title: '시험' }); } finally { if (outer) parent.insertBefore(outer, next); }
    return h; });
  const p2 = await context.newPage();
  await p2.route('**/*', r => r.request().url().startsWith('data:') ? r.continue() : r.fulfill({ status: 404, body: '' }));
  await p2.setContent(html, { waitUntil: 'load' });
  const exp = (await p2.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
  await p2.close();
  check('전달본(내보내기)에 제외 목록이 없다', !exp.includes('제외된 키워드') && !exp.includes('같은 종류의 다른 상품'), exp.slice(0, 120));
  check('전달본에 상품명 후보(밀크초콜릿)는 있다', exp.includes('밀크초콜릿'));
  check('페이지 오류 0', errs.length === 0, errs.join(' | ').slice(0, 300));
  await page.close(); if (!cdp) await browser.close(); server.close();
  const failed = results.filter(r => !r).length;
  console.log('\n결과: ' + (results.length - failed) + ' 통과 · ' + failed + ' 실패');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
