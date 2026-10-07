'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const external = [], writes = [], errors = [];
  await context.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && !request.url().endsWith('/session'))
      writes.push(new URL(request.url()).pathname);
  });
  try {
    await page.clock.install({ time: new Date(cfg.now) });
    await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({ contentType: 'application/javascript',
      body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
        JSON.stringify({ code: cfg.code, codeVerifier: 'V'.repeat(42) + 'A' }) + ')};' }));
    await page.goto(cfg.base + '/naver/');
    await page.waitForSelector('#s-watch.on #kpis .kpi');
    assert.equal(await page.locator('#issues .iss .act button').count(), 0);
    // 개편(2026-10-06): 짝 확인·일괄 확정은 이관 현황 · 복구 조회는 설정 › 시스템
    assert.equal(await page.locator('#s-watch #linksCard, #s-watch #collectionControls').count(), 0);
    await page.click('[data-go="/naver/transfers"]');
    await page.waitForSelector('#s-transfers.on #linksToggle');
    await page.click('#linksToggle');
    // 접힌 카드는 조회하지 않는다. 펼친 뒤 실제 짝 응답이 그린 확정 버튼까지 기다린다.
    await page.waitForSelector('#s-transfers.on #confirmAuto:not([hidden])');
    assert.equal(await page.getByRole('button', { name: '아님', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '캠페인 이름 보기', exact: true }).count(), 0);
    await page.click('#confirmAuto');
    await page.waitForSelector('#m-confirm-auto.on #ca-ok');
    assert.deepEqual(writes, [], '확인창의 「확정」 전에는 보내지 않는다(D5)');
    const confirmation = page.waitForResponse(r => r.url().endsWith('/links/confirm'));
    await page.click('#ca-ok');
    assert.equal((await confirmation).status(), 200);
    await page.waitForSelector('#confirmAuto[hidden]', { state: 'attached' });
    await page.click('#menuSettings');
    await page.waitForSelector('#s-settings.on');
    await page.click('[data-sp="sys"]');
    assert.equal(await page.isVisible('#collectionControls'), true);
    assert.equal(await page.isVisible('#collectNow'), false);
    await page.click('#collectionControls > summary');
    const request = page.waitForResponse(r => r.url().endsWith('/collection/request'));
    await page.click('#collectNow');
    assert.equal((await request).status(), 200);
    await page.waitForFunction(() => document.getElementById('collectionStatus').textContent.includes('조회 접수됨'));
    assert.deepEqual(writes, ['/api/naver-auto/links/confirm', '/api/naver-auto/collection/request']);
    assert.deepEqual(external, []); assert.deepEqual(errors, []);
    console.log('verified-collection-screen-ok');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
