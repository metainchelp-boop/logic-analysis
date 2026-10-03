'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch(cfg.executablePath ? {executablePath:cfg.executablePath} : {});
  const context = await browser.newContext({locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const page = await context.newPage(), errors = [], external = [], methods = [], runtimeMethods = [], checks = [];
  let injected = null, runtimeResponses = 0;
  const pending = [];
  page.setDefaultTimeout(7000);
  await context.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(new URL(route.request().url()).origin); return route.abort();
  });
  await page.route('**/api/naver-auto/health?runtime=1', route => {
    runtimeMethods.push(route.request().method());
    if (injected === 'failure') return route.abort('failed');
    if (injected === 'pending') { pending.push(route); return; }
    if (injected === null) return route.continue();
    return route.fulfill({status:200,contentType:'application/json',json:{runtime:injected}});
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => methods.push(request.method()));
  page.on('response', response => {
    const url = new URL(response.url());
    if (url.pathname === '/api/naver-auto/health' && url.search === '?runtime=1') runtimeResponses++;
  });
  const status = page.locator('#runtimeStatus');
  const base = {state:'collecting',indicator:'green',reason_code:'COLLECTING',
    verified_at:cfg.now,valid_for_seconds:25,retry_at:null};
  async function indicator(value, phrase) {
    await page.waitForFunction(([wanted, pattern]) => {
      const element = document.querySelector('#runtimeStatus');
      const label = document.querySelector('#runtimeLabel');
      return element && element.dataset.indicator === wanted && label &&
        (!pattern || new RegExp(pattern).test(label.textContent));
    }, [value,phrase ? phrase.source : null]);
    assert.equal(await status.isVisible(),true);
    if (phrase) assert.match(await page.textContent('#runtimeLabel'),phrase);
  }
  async function assertNoOverflow() {
    const overflow = await page.evaluate(() => ({page:document.documentElement.scrollWidth > window.innerWidth,
      header:document.querySelector('#runtimeStatus').scrollWidth > document.querySelector('#runtimeStatus').clientWidth}));
    assert.deepEqual(overflow,{page:false,header:false});
  }
  async function capture(name) {
    if (!cfg.shots) return;
    fs.mkdirSync(cfg.shots,{recursive:true});
    await page.screenshot({path:path.join(cfg.shots,name),fullPage:true});
  }
  async function poll(value, color, phrase) {
    injected = value;
    const before = runtimeMethods.length;
    const isRuntime = item => new URL(item.url()).pathname === '/api/naver-auto/health' &&
      new URL(item.url()).search === '?runtime=1';
    const reply = value === 'failure' ? page.waitForEvent('requestfailed',{predicate:isRuntime}) :
      page.waitForResponse(isRuntime);
    await page.clock.runFor(15001);
    const response = await reply;
    if (typeof response.finished === 'function') await response.finished();
    assert.ok(runtimeMethods.length > before,'정기 재조회가 있어야 합니다');
    await indicator(color,phrase);
  }
  try {
    await page.clock.install({time:new Date(cfg.now)});
    const meReply = page.waitForResponse(response => new URL(response.url()).pathname === '/api/naver-auto/me');
    await page.goto(cfg.base + '/naver/dashboard');
    const me = await (await meReply).json();
    assert.equal(me.scope,'MINE');
    assert.equal(me.idx,100);
    await indicator('green',/수집/);
    assert.equal(await status.getAttribute('role'),'status');
    assert.equal(await status.getAttribute('aria-live'),'polite');
    await capture('runtime-status-desktop-green.png');
    checks.push('actual-staff-wsgi-get-collecting-green');

    await poll({...base,state:'waiting',reason_code:'WAITING'},'green',/대기/);
    checks.push('normal-wait-green');
    await poll({...base,state:'rate_paused',indicator:'red',reason_code:'RATE_LIMITED',
      retry_at:'2026-10-04T00:00:00+09:00'},'red',/제한|정지|중단/);
    assert.match(await page.textContent('#runtimeDetail'),/대기|확인/);
    await page.setViewportSize({width:390,height:844});
    await assertNoOverflow();
    await capture('runtime-status-mobile-red.png');
    await page.setViewportSize({width:1280,height:720});
    checks.push('rate-pause-red');
    await poll({...base,state:'stale',indicator:'red',reason_code:'STALE',valid_for_seconds:0},'red',/확인/);
    checks.push('server-stale-red');

    await poll({...base,valid_for_seconds:2},'green',/수집/);
    const repliesBeforeExpiry = runtimeResponses;
    injected = 'pending';
    await page.clock.runFor(2100);
    await indicator('red',/확인/);
    assert.equal(runtimeResponses,repliesBeforeExpiry,'새 응답이 없으면 기존 녹색의 유효기간 만료 후 빨강이어야 합니다');
    await Promise.all(pending.splice(0).map(route => route.abort('failed')));
    checks.push('client-expiry-red-without-response');
    await poll({...base},'green',/수집/);
    await poll('failure','red',/확인/);
    checks.push('fetch-failure-red');

    const secret = 'PRIVATE_RUNTIME_SECRET_<img src=x onerror=alert(1)>';
    await poll({...base,state:secret,reason_code:secret,retry_at:secret,private_key:secret},'red',/확인/);
    assert.equal((await status.textContent()).includes(secret),false);
    assert.equal((await page.textContent('body')).includes(secret),false);
    assert.equal(await status.locator('img,script').count(),0);
    checks.push('unknown-and-secret-not-rendered');
    await poll({...base},'green',/수집/);

    await page.evaluate(() => { window.__runtimeNode=document.querySelector('#runtimeStatus'); });
    for (const destination of ['/naver/','/naver/reports','/naver/transfers','/naver/automation','/naver/dashboard']) {
      await page.click('[data-go="' + destination + '"]');
      await page.waitForURL(cfg.base + destination);
      assert.equal(await status.isVisible(),true);
      assert.equal(await page.evaluate(() => window.__runtimeNode===document.querySelector('#runtimeStatus')),true);
    }
    checks.push('shared-header-survives-all-staff-tabs');
    await page.setViewportSize({width:390,height:844});
    await assertNoOverflow();
    assert.equal(await status.isVisible(),true);
    checks.push('390px-no-horizontal-overflow');
    assert.ok(runtimeMethods.length >= 9);
    assert.ok(runtimeMethods.every(method => method === 'GET'));
    assert.ok(methods.every(method => method === 'GET'));
    assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    checks.push('get-only-zero-writes-zero-external-requests');
    console.log('runtime-status-screen-ok ' + JSON.stringify(checks));
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode=1; });
