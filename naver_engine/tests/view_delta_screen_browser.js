'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch(cfg.executablePath ? {executablePath: cfg.executablePath} : {});
  const ctx = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
  const page = await ctx.newPage(), errors = [], external = [], writes = [], measurements = [], checks = [];
  page.setDefaultTimeout(10000);
  await ctx.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() !== 'GET' && !request.url().endsWith('/session')) writes.push(request.url());
  });
  const boardUrl = response => new URL(response.url()).pathname === '/api/naver-auto/board';
  let fault = null, boardRequests = 0, held = null;
  await page.route('**/api/naver-auto/board?**', async route => {
    boardRequests++;
    const use = fault; fault = null;
    if (use === 'network') return route.abort('connectionfailed');
    if (use === 'reject-opt-in') return route.fulfill({status: 400, json: {error: 'bad-query'}});
    const url = new URL(route.request().url());
    if (use === 'full') url.searchParams.delete('view_cursor');
    if (use === 'legacy') { url.searchParams.delete('view_sync'); url.searchParams.delete('view_cursor'); }
    const response = await route.fetch({url: url.toString()});
    if (use === 'hold') await new Promise(resolve => { held = resolve; });
    if (use === 'invalid') {
      const data = await response.json();
      return route.fulfill({response, json: {...data, mode: 'delta', base_cursor: 'wrong-base',
        data: {selection: 'all'}, rows: {key_fields: ['possibility_id'], upsert: [], removed: [], order: []}}});
    }
    if (use === 'invalid-order') {
      const data = await response.json();
      return route.fulfill({response, json: {...data, mode: 'delta', data: {selection: 'all'},
        rows: {key_fields: ['possibility_id'], upsert: [{possibility_id: 11, name: '절대 표시하면 안 되는 잘못된 정정'}],
          removed: [], order: ['[11]', '[12]', '[13]', '[14]', '[999]']}}});
    }
    return route.fulfill({response});
  });
  async function control(operation) {
    const response = await ctx.request.post(cfg.base + '/__view_delta_test__/' + operation,
      {headers: {Origin: cfg.base}});
    assert.equal(response.status(), 200, '합성 자료 변경: ' + operation);
    assert.deepEqual(await response.json(), {ok: true});
  }
  async function settled(status = 'current', target = page, name = 'watch') {
    await target.waitForFunction(([name, status]) => document.querySelector('#' + name + 'Sync').dataset.status === status,
      [name, status]);
  }
  async function ids() {
    return page.locator('#tbody tr[data-pid]').evaluateAll(rows => rows.map(row => Number(row.dataset.pid)).sort());
  }
  async function boardRefresh() {
    const response = page.waitForResponse(boardUrl);
    if (await page.locator('#watchReload').count() && !cfg.baseline) await page.click('#watchReload');
    else await page.click('[data-go="/naver/"]');
    const result = await response;
    await result.finished();
    if (!cfg.baseline) await page.waitForFunction(() => document.querySelector('#watchSync').dataset.status !== 'checking');
    else await page.waitForTimeout(100);
    return result;
  }
  try {
    await page.clock.install({time: new Date(cfg.now)});
    const firstReply = page.waitForResponse(boardUrl);
    await page.goto(cfg.base + '/naver/');
    const first = await firstReply;
    await page.waitForSelector('#tbody tr[data-pid="11"]');
    await page.click('#tblChips [data-f="all"]');
    await page.evaluate(() => { window.__deltaRow = document.querySelector('#tbody tr[data-pid="11"]'); });
    const unchanged = await boardRefresh();
    assert.equal(await page.evaluate(() => window.__deltaRow === document.querySelector('#tbody tr[data-pid="11"]')),
      true, '반복 서버 조회는 변하지 않은 실제 관제 행 노드를 보존해야 합니다');
    measurements.push({view: 'board', full_bytes: (await first.body()).length,
      unchanged_bytes: (await unchanged.body()).length, mode: (await unchanged.json()).mode});
    assert.equal((await unchanged.json()).mode, 'unchanged');
    checks.push('unchanged-row-identity');
    const original = (await first.json()).data;
    assert.ok((await unchanged.body()).length < (await first.body()).length / 2, '실제 unchanged 응답 바이트 감소');
    await page.fill('#q', original.rows.find(row => row.possibility_id === 11).name);
    await page.focus('#q');
    const focusReply = page.waitForResponse(boardUrl);
    await page.locator('#watchReload').dispatchEvent('click');
    await (await focusReply).finished(); await settled();
    assert.equal(await page.locator('#q').inputValue(), original.rows.find(row => row.possibility_id === 11).name);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'q', '변경 없는 조회는 입력 초점을 보존');
    await page.fill('#q', '');
    await page.evaluate(() => { window.scrollTo(0, 500); window.__deltaScroll = window.scrollY; });
    assert.ok(await page.evaluate(() => window.__deltaScroll > 0));
    const scrollReply = page.waitForResponse(boardUrl);
    await page.locator('#watchReload').dispatchEvent('click');
    await (await scrollReply).finished(); await settled();
    assert.equal(await page.evaluate(() => window.scrollY === window.__deltaScroll), true,
      '같은 범위의 변경 없는 조회는 스크롤 위치를 보존');
    checks.push('unchanged-scroll-preserved');
    await page.evaluate(() => { window.__unchangedOther = document.querySelector('#tbody tr[data-pid="12"]'); });
    await control('correct');
    const correction = await boardRefresh(), patch = await correction.json();
    assert.equal(patch.mode, 'delta');
    assert.deepEqual(patch.rows.upsert.map(row => row.possibility_id), [11]);
    assert.match(await page.locator('#tbody tr[data-pid="11"]').innerText(), /43,210/);
    assert.equal(await page.evaluate(() => window.__unchangedOther === document.querySelector('#tbody tr[data-pid="12"]')), true);
    measurements.push({view: 'board-correction', bytes: (await correction.body()).length,
      mode: patch.mode, upsert_rows: patch.rows.upsert.length, removed_rows: patch.rows.removed.length});
    checks.push('query-focus-preserved', 'single-row-correction');
    await control('add');
    const added = await boardRefresh();
    assert.equal((await added.json()).mode, 'delta');
    assert.ok((await ids()).includes(15));
    assert.equal(await page.evaluate(() => window.__unchangedOther === document.querySelector('#tbody tr[data-pid="12"]')), true);
    await control('remove');
    const removed = await boardRefresh();
    assert.deepEqual((await removed.json()).rows.removed, ['[15]']);
    assert.equal((await ids()).includes(15), false);
    checks.push('add-remove-current-order');

    // 늦는 같은 범위 조회: 현재 행은 유지하고 클릭 연타는 한 요청으로 합친다.
    const beforeHold = boardRequests;
    fault = 'hold'; held = null;
    await page.click('#watchReload');
    while (!held) await new Promise(resolve => setTimeout(resolve, 10));
    await page.click('#watchReload');
    assert.equal(boardRequests, beforeHold + 1);
    await settled('checking');
    assert.equal(await page.locator('#tbody tr[data-pid="11"]').isVisible(), true);
    const release = held; held = null; release(); await settled();
    checks.push('slow-same-scope-retain-and-dedupe');

    // 통신 실패는 이전 확인 시각과 실패를 드러낸 상태에서만 기존 행을 남긴다.
    fault = 'network';
    await page.click('#watchReload'); await settled('stale');
    assert.equal(await page.locator('#tbody tr[data-pid="11"]').isVisible(), true);
    assert.match(await page.locator('#watchSync').innerText(), /최신화 실패.*이전 확인 자료/);
    await boardRefresh(); await settled();
    checks.push('network-failure-visible-stale');

    // 잘못된 기준 cursor는 부분 반영 없이 cursor 없는 실제 full GET 한 번으로 회복한다.
    fault = 'invalid'; const beforeInvalid = boardRequests;
    await boardRefresh(); await settled();
    assert.equal(boardRequests, beforeInvalid + 2);
    assert.equal(await page.locator('#tbody tr[data-pid="11"]').count(), 1);
    await page.evaluate(() => {
      window.__invalidPaint = false;
      window.__invalidObserver = new MutationObserver(() => {
        if (document.querySelector('#tbody').textContent.includes('절대 표시하면 안 되는')) window.__invalidPaint = true;
      });
      window.__invalidObserver.observe(document.querySelector('#tbody'), {subtree: true, childList: true, characterData: true});
    });
    fault = 'invalid-order'; const beforeOrderInvalid = boardRequests;
    await boardRefresh(); await settled();
    assert.equal(boardRequests, beforeOrderInvalid + 2);
    assert.equal(await page.evaluate(() => { window.__invalidObserver.disconnect(); return window.__invalidPaint; }), false);
    checks.push('late-invalid-delta-not-partially-painted');
    fault = 'full';
    await page.evaluate(() => { window.__fullRow = document.querySelector('#tbody tr[data-pid="11"]'); });
    const fullFallback = await boardRefresh();
    assert.equal((await fullFallback.json()).mode, 'full');
    assert.equal(await page.evaluate(() => window.__fullRow === document.querySelector('#tbody tr[data-pid="11"]')), true);
    fault = 'reject-opt-in'; const beforeLegacy = boardRequests;
    await boardRefresh(); await settled();
    assert.equal(boardRequests, beforeLegacy + 2);
    fault = 'legacy'; const legacy = await boardRefresh();
    assert.equal((await legacy.json()).mode, undefined);
    assert.equal(await page.locator('#tbody tr[data-pid="11"]').count(), 1);
    checks.push('invalid-delta-atomic-recovery', 'full-fallback-row-identity', 'legacy-payload-and-rejected-opt-in');

    // 실제 대시보드 응답과 재진입 검증. 숨긴 탭의 행은 새 성공 응답 전 보이지 않는다.
    const dashboardFirst = page.waitForResponse(response => response.url().includes('/dashboard?'));
    await page.click('[data-go="/naver/dashboard"]'); await settled('current', page, 'dashboard');
    const dashFull = await dashboardFirst;
    const dashboardSecond = page.waitForResponse(response => response.url().includes('/dashboard?'));
    await page.click('#dashboardReload'); await settled('current', page, 'dashboard');
    const dashSame = await dashboardSecond;
    assert.equal((await dashSame.json()).mode, 'unchanged');
    measurements.push({view: 'dashboard', full_bytes: (await dashFull.body()).length,
      unchanged_bytes: (await dashSame.body()).length});
    fault = 'network';
    await page.click('[data-go="/naver/"]'); await settled('error');
    assert.equal(await page.locator('#tbody tr[data-pid="11"]').isVisible(), false);
    await page.locator('#watchSync button').click(); await settled();
    await page.click('[data-go="/naver/dashboard"]'); await settled('current', page, 'dashboard');
    checks.push('hidden-reentry-failure-does-not-reveal-cache');
    fault = 'hold'; held = null;
    await page.click('[data-go="/naver/"]');
    while (!held) await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(await page.locator('#s-watch').evaluate(node => node.classList.contains('view-unverified')), true);
    assert.equal(await page.locator('#tbody tr[data-pid="11"]').isVisible(), false);
    held(); held = null; await settled();
    checks.push('actual-dashboard-unchanged', 'tab-reentry-hidden-until-verified');

    // 이전 범위의 늦은 성공은 새 담당자 화면을 덮을 수 없다.
    fault = 'hold'; held = null;
    await page.click('#watchReload');
    while (!held) await new Promise(resolve => setTimeout(resolve, 10));
    await page.selectOption('#scope', 'person:101'); await settled();
    assert.deepEqual(await ids(), [12]);
    held(); held = null;
    await page.waitForTimeout(50);
    assert.deepEqual(await ids(), [12]);
    await page.selectOption('#scope', 'all'); await settled();
    assert.ok((await ids()).includes(11));
    checks.push('scope-change-discards-late-response');

    const accountsFirst = page.waitForResponse(response => response.url().includes('/accounts?'));
    await page.click('[data-go="/naver/transfers"]'); await settled('current', page, 'inventory');
    const accountFull = await accountsFirst;
    await page.evaluate(() => { window.__inventoryRow = document.querySelector('#inventoryRows tr'); });
    const accountsSecond = page.waitForResponse(response => response.url().includes('/accounts?'));
    await page.click('#inventoryReload'); await settled('current', page, 'inventory');
    const accountSame = await accountsSecond;
    assert.equal((await accountSame.json()).mode, 'unchanged');
    assert.equal(await page.evaluate(() => window.__inventoryRow === document.querySelector('#inventoryRows tr')), true);
    measurements.push({view: 'accounts', full_bytes: (await accountFull.body()).length,
      unchanged_bytes: (await accountSame.body()).length});
    await control('inventory-correct');
    const accountChange = page.waitForResponse(response => response.url().includes('/accounts?'));
    await page.click('#inventoryReload'); await settled('current', page, 'inventory');
    assert.equal((await (await accountChange).json()).rows.upsert.length, 1);
    assert.match(await page.locator('#inventoryRows').innerText(), /54,321/);
    checks.push('actual-accounts-unchanged-and-correction');

    const reportsFirst = page.waitForResponse(response => response.url().includes('/reports?'));
    await page.click('[data-go="/naver/reports"]'); await settled('current', page, 'reports');
    const reportFull = await reportsFirst;
    await page.evaluate(() => { window.__reportRow = document.querySelector('#reportsRows [data-report]'); });
    const reportsSecond = page.waitForResponse(response => response.url().includes('/reports?'));
    await page.click('#reportsReload'); await settled('current', page, 'reports');
    const reportSame = await reportsSecond;
    assert.equal((await reportSame.json()).mode, 'unchanged');
    assert.equal(await page.evaluate(() => window.__reportRow === document.querySelector('#reportsRows [data-report]')), true);
    measurements.push({view: 'reports', full_bytes: (await reportFull.body()).length,
      unchanged_bytes: (await reportSame.body()).length});
    await control('report-correct');
    const revised = page.waitForResponse(response => response.url().includes('/reports?'));
    await page.click('#reportsReload'); await settled('current', page, 'reports');
    const reportDelta = await (await revised).json();
    assert.equal(reportDelta.mode, 'delta');
    assert.equal(reportDelta.rows.upsert.length, 1);
    assert.equal(await page.locator('#reportsRows [data-report="21"]').count(), 0);
    assert.equal(await page.locator('#reportsRows [data-report="1000"]').count(), 1);
    assert.equal(await page.locator('#reportsRows > [data-report]').count(), 20);
    await page.locator('#reportsPages button', {hasText: '다음 보고서'}).click();
    await settled('current', page, 'reports');
    assert.match(await page.locator('#reportsStatus').innerText(), /2페이지/);
    await control('reports-shrink');
    await page.click('#reportsReload'); await settled('current', page, 'reports');
    assert.match(await page.locator('#reportsStatus').innerText(), /1건.*1페이지/);
    assert.equal(await page.locator('#reportsRows > [data-report]').count(), 1);
    checks.push('actual-report-identity', 'report-revision-replaces-period', 'report-missing-page-first-page-recovery');

    // 실제 직원 세션의 조직 stale 오류: fallback 없이 모든 이전 범위 자료를 지운다.
    const staffCtx = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
    await staffCtx.route('**/*', route => route.request().url().startsWith(cfg.base + '/') ? route.continue() : route.abort());
    const staff = await staffCtx.newPage();
    await staff.clock.install({time: new Date(cfg.now)});
    await staff.route('**/naver/sso-bootstrap.js', route => route.fulfill({contentType: 'application/javascript',
      body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
        JSON.stringify({code: cfg.staffCode, codeVerifier: 'V'.repeat(42) + 'A'}) + ')};'}));
    await staff.goto(cfg.base + '/naver/'); await settled('current', staff);
    assert.ok(await staff.locator('#tbody tr[data-pid]').count());
    await control('org-stale');
    let staffBoardRequests = 0;
    staff.on('request', request => { if (new URL(request.url()).pathname === '/api/naver-auto/board') staffBoardRequests++; });
    await staff.click('#watchReload'); await settled('error', staff);
    assert.equal(staffBoardRequests, 1);
    assert.equal(await staff.locator('#tbody tr[data-pid]').count(), 0);
    assert.match(await staff.locator('#watchSync').innerText(), /현재 권한·조직 자료/);
    await staffCtx.close();
    await control('org-fresh');
    checks.push('actual-authority-stale-purges-without-fallback');

    // 자정을 넘겨 도착한 옛 날짜 응답은 버리고 새 날짜를 cursor 없이 확인한다.
    await control('near-midnight');
    const midnightCtx = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
    await midnightCtx.route('**/*', route => {
      if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
      external.push(route.request().url()); return route.abort();
    });
    const midnight = await midnightCtx.newPage();
    midnight.on('pageerror', error => errors.push(error.message));
    const late = new Date(cfg.now.slice(0, 10) + 'T23:59:40+09:00');
    await midnight.clock.install({time: late});
    const midnightRequests = [], midnightReplies = [];
    let holdMidnight = false, releaseMidnight;
    await midnight.route('**/api/naver-auto/board?**', async route => {
      midnightRequests.push(new URL(route.request().url()));
      const response = await route.fetch();
      midnightReplies.push(await response.json());
      if (holdMidnight) { holdMidnight = false; await new Promise(resolve => { releaseMidnight = resolve; }); }
      await route.fulfill({response});
    });
    await midnight.goto(cfg.base + '/naver/'); await settled('current', midnight);
    holdMidnight = true;
    await midnight.click('#watchReload');
    while (!releaseMidnight) await new Promise(resolve => setTimeout(resolve, 10));
    await control('next-day');
    await midnight.clock.setSystemTime(new Date(late.getTime() + 40000));
    releaseMidnight(); await settled('current', midnight);
    assert.equal(midnightRequests.length, 3);
    assert.equal(midnightRequests[2].searchParams.has('view_cursor'), false);
    assert.equal(midnightReplies[2].mode, 'full');
    assert.notEqual(midnightReplies[0].checked_at.slice(0, 10), midnightReplies[2].checked_at.slice(0, 10));
    await midnightCtx.close();
    checks.push('midnight-late-response-rechecks-without-cursor');

    const stores = await page.evaluate(() => ({local: Object.keys(localStorage), session: Object.keys(sessionStorage)}));
    assert.deepEqual(stores, {local: [], session: ['naverWatch.session']});
    checks.push('no-persistent-view-data');
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.deepEqual(writes, []);
    console.log(JSON.stringify({result: 'view-delta-screen-ok', checks, measurements}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
