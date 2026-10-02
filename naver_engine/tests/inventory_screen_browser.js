'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const {chromium} = require('playwright');
const cfg = JSON.parse(process.argv[2]);
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
  const page = await context.newPage(), errors = [], writes = [], external = [];
  let code = cfg.ceo;
  await context.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({contentType: 'application/javascript',
    body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
      JSON.stringify({code, codeVerifier: 'V'.repeat(42) + 'A'}) + ')};'}));
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() !== 'GET' && !r.url().endsWith('/session')) writes.push(r.url()); });
  try {
    await page.clock.install({time: new Date(cfg.now)});
    await page.goto(cfg.base + '/naver/');
    await page.waitForSelector('#s-watch.on');
    assert.equal(await page.locator('#inventoryCard').isVisible(), false);
    const menu = await page.locator('.menu button').allTextContents();
    assert.ok(menu.indexOf('📋 이관 현황') === menu.indexOf('📄 보고서') + 1);
    await page.getByRole('button', {name: '📋 이관 현황', exact: true}).click();
    await page.waitForURL(cfg.base + '/naver/transfers');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.includes('4계정'));
    assert.equal(await page.locator('#s-watch').isVisible(), false);
    assert.equal(await page.locator('#inventoryCard').isVisible(), true);
    assert.equal(await page.locator('#inventoryRows tr').count(), 4);
    assert.match(await page.textContent('#inventoryRows'), /4,116원/);
    assert.doesNotMatch(await page.textContent('#inventoryRows'), /4,116\.83|4,117원/);
    assert.match(await page.textContent('#inventoryCount'), /매칭 2/);
    assert.match(await page.textContent('#inventoryCount'), /업체 미확인 2/);
    const options = await page.locator('#scope option').allTextContents();
    assert.ok(options.some(s => /1계정/.test(s)));
    assert.ok(!options.some(s => /팀 ·|퇴사|정지/.test(s)));
    await page.selectOption('#inventoryWorkflow', '환불완료');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.startsWith('1 /'));
    assert.equal(await page.locator('#inventoryRows tr').count(), 1);
    assert.match(await page.textContent('#inventoryRows'), /환불완료/);
    await page.selectOption('#inventoryWorkflow', 'all');
    await page.selectOption('#inventoryMapping', 'no_erp_record');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.startsWith('2 /'));
    assert.equal(await page.locator('#inventoryRows button').count(), 0);
    await page.selectOption('#inventoryMapping', 'all');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.startsWith('4 /'));
    await page.selectOption('#scope', 'person:3');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.startsWith('1 /'));
    assert.equal(page.url(), cfg.base + '/naver/transfers');
    await page.selectOption('#scope', 'all');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.startsWith('4 /'));
    await page.getByRole('button', {name: '🛰 관제', exact: true}).first().click();
    await page.waitForSelector('#s-watch.on');
    assert.equal(await page.locator('#inventoryCard').isVisible(), false);
    await page.goBack();
    await page.waitForSelector('#s-transfers.on');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.startsWith('4 /'));
    if (cfg.shots) {
      fs.mkdirSync(cfg.shots, {recursive: true});
      await page.locator('#inventoryCard').screenshot({path: path.join(cfg.shots, 'inventory-owner.png')});
    }
    code = cfg.staff;
    await page.goto(cfg.base + '/naver/transfers');
    await page.waitForFunction(() => document.querySelector('#inventoryCount').textContent.includes('1계정'));
    assert.equal(await page.locator('#inventoryRows tr').count(), 1);
    assert.equal(await page.locator('#scope').isVisible(), false);
    assert.match(await page.textContent('#me'), /1계정/);
    assert.match(await page.textContent('#inventoryCount'), /업체 미확인 0/);
    if (cfg.shots) await page.locator('#inventoryCard').screenshot({path: path.join(cfg.shots, 'inventory-staff.png')});
    assert.deepEqual(writes, []); assert.deepEqual(external, []); assert.deepEqual(errors, []);
    console.log('inventory-screen-ok: all, refund, no-erp, roster-count, own-only, no-writes');
  } finally { await context.close(); await browser.close(); }
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
