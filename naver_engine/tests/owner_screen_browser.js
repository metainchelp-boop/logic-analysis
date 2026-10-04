/* 읽기 전용 검증판: 기존 실제 화면/중계/엔진 시험 서버에서 Chromium으로 확인한다. */
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
    if (request.method() === 'POST' && !request.url().endsWith('/session') && !request.url().endsWith('/session/refresh'))
      writes.push(new URL(request.url()).pathname);
  });
  try {
    await page.clock.install({ time: new Date(cfg.now) });
    await page.goto(cfg.base + '/naver/');
    await page.waitForSelector('#s-blocked.on');
    assert.ok((await page.textContent('#b-p')).includes('네이버 관제(읽기 전용)'));
    await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({ contentType: 'application/javascript',
      body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
        JSON.stringify({ code: cfg.code, codeVerifier: 'V'.repeat(42) + 'A' }) + ')};' }));
    await page.goto(cfg.base + '/naver/');
    await page.waitForSelector('#s-watch.on #kpis .kpi');
    await page.waitForSelector('#issues .iss');
    assert.equal(await page.isVisible('#verificationNotice'), true);
    assert.ok((await page.textContent('#verificationNotice')).includes('자료 미확인은 0이나 정상으로 표시하지 않습니다'));
    assert.equal(await page.locator('#issues .iss .act button').count(), 0);
    const read = path => page.evaluate(async path => {
      const session = JSON.parse(sessionStorage.getItem('naverWatch.session'));
      const response = await fetch('/api/naver-auto' + path, { headers: { Authorization: 'Bearer ' + session.token } });
      return response.json();
    }, path);
    const me = await read('/me');
    assert.equal(me.idx, 0); assert.equal(me.owner_verification, true);
    const bellBefore = await read('/bell');
    await page.click('#bell');
    await page.waitForSelector('#drawer.on .bitem');
    assert.equal(await page.isVisible('#bellAll'), false);
    await page.locator('#drawer .bitem').first().click();
    await page.waitForSelector('#s-watch.on #kpis .kpi');
    assert.deepEqual(await read('/bell'), bellBefore);
    await page.click('#linksToggle');
    await page.waitForSelector('#linksBody:not([hidden]) > *');
    assert.equal(await page.locator('#linksBody .act button').count(), 0);
    await page.click('#menuSettings');
    await page.waitForSelector('#s-settings.on #sp-th table');
    assert.equal(await page.locator('#sp-th input, #sp-th button').count(), 0);
    assert.ok((await page.textContent('#set-ps')).includes('점검 기준을 변경할 수 없습니다'));
    await page.click('[data-sp="time"]');
    assert.ok((await page.textContent('#sp-time')).includes('알림 전송·자동입찰은 꺼져 있습니다'));
    assert.ok(!(await page.textContent('#sp-time')).includes('비서방으로 갑니다'));
    await page.click('[data-sp="sys"]');
    assert.equal(await page.locator('#sp-sys .act button').count(), 0);
    assert.deepEqual(writes, [], '화면 탐색·알림 클릭은 업무 POST를 보내면 안 됩니다.');
    for (const path of ['/issues/1/ack', '/links/confirm', '/bell/read-all', '/settings/thresholds', '/holds/org/confirm']) {
      const response = await page.evaluate(async path => {
        const session = JSON.parse(sessionStorage.getItem('naverWatch.session'));
        const result = await fetch('/api/naver-auto' + path, { method: 'POST',
          headers: { Authorization: 'Bearer ' + session.token, 'Content-Type': 'application/json' }, body: '{}' });
        return { status: result.status, body: await result.json() };
      }, path);
      assert.deepEqual(response, { status: 403, body: { error: 'verification-read-only' } });
    }
    assert.deepEqual(external, []); assert.deepEqual(errors, []);
    console.log('owner-screen-ok: banner, menu-help, no-business-buttons, no-ui-writes, direct-post-403');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
