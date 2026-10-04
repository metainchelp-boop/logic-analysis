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
    await page.waitForSelector('#confirmAuto:not([hidden])');
    assert.equal(await page.isVisible('#collectionControls'), true);
    assert.equal(await page.locator('#issues .iss .act button').count(), 0);
    await page.click('#linksToggle');
    await page.waitForSelector('#linksBody:not([hidden]) > *');
    assert.equal(await page.getByRole('button', { name: '아님', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '캠페인 이름 보기', exact: true }).count(), 0);
    const confirmation = page.waitForResponse(r => r.url().endsWith('/links/confirm'));
    await page.click('#confirmAuto');
    assert.equal((await confirmation).status(), 200);
    await page.waitForSelector('#confirmAuto[hidden]', { state: 'attached' });
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
