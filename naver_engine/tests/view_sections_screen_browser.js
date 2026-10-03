'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch(cfg.executablePath ? {executablePath: cfg.executablePath} : {});
  const ctx = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
  const page = await ctx.newPage(), errors = [], external = [], writes = [], checks = [];
  page.setDefaultTimeout(10000);
  await ctx.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() !== 'GET' && !request.url().endsWith('/session')) writes.push(request.url());
  });
  async function settled(name = 'inventory', status = 'current', target = page) {
    await target.waitForFunction(([name, status]) => document.querySelector('#' + name + 'Sync').dataset.status === status,
      [name, status]);
  }
  const accountsUrl = response => new URL(response.url()).pathname === '/api/naver-auto/accounts';
  const boardUrl = response => new URL(response.url()).pathname === '/api/naver-auto/board';
  async function boardAction(action) {
    const reply = page.waitForResponse(boardUrl);
    await action(); const response = await reply;
    await response.finished(); await settled('watch'); return response;
  }
  async function control(operation) {
    const response = await ctx.request.post(cfg.base + '/__view_delta_test__/' + operation,
      {headers: {Origin: cfg.base}});
    assert.equal(response.status(), 200); assert.deepEqual(await response.json(), {ok: true});
  }
  async function accountAction(action) {
    const reply = page.waitForResponse(accountsUrl);
    await action(); const response = await reply;
    await response.finished(); await settled(); return response;
  }
  try {
    await page.clock.install({time: new Date(cfg.now)});
    await page.goto(cfg.base + '/naver/transfers'); await settled();
    assert.equal(await page.locator('#managedCoverage').isVisible(), true);
    assert.equal(await page.locator('#inventoryCard').isVisible(), false,
      '처음 이관 현황은 전산 실관리·누락 대조만 표시해야 합니다');
    checks.push('default-coverage-only');
    assert.equal(await page.locator('#inventoryAccountsTab').count(), 1, '계정 분류 전환 버튼이 있어야 합니다');
    let release, received;
    const held = new Promise(resolve => { received = resolve; });
    await page.route('**/api/naver-auto/accounts?**', async route => {
      const response = await route.fetch();
      await new Promise(resolve => { release = resolve; received(); });
      await route.fulfill({response});
    });
    await page.click('#inventoryAccountsTab'); await held;
    assert.equal(await page.locator('#inventoryCard').isVisible(), false, '새 영역은 서버 재확인 전 숨겨야 합니다');
    assert.equal(await page.locator('#managedCoverage').isVisible(), false);
    release(); await settled(); await page.unroute('**/api/naver-auto/accounts?**');
    assert.equal(await page.locator('#inventoryCard').isVisible(), true);
    assert.equal(await page.locator('#managedCoverage').isVisible(), false);
    assert.equal(await page.locator('#inventoryAccountsTab').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('#inventoryReload').isVisible(), true);
    const back = page.waitForResponse(accountsUrl);
    await page.focus('#inventoryCoverageTab'); await page.keyboard.press('Enter');
    await (await back).finished(); await settled();
    assert.equal(await page.locator('#managedCoverage').isVisible(), true);
    assert.equal(await page.locator('#inventoryCard').isVisible(), false);
    assert.equal(await page.locator('#inventoryReload').isVisible(), true);
    checks.push('switch-revalidates-before-reveal', 'keyboard-switch-and-common-refresh');
    await accountAction(() => page.click('#inventoryAccountsTab'));
    await accountAction(() => page.selectOption('#inventoryMapping', 'no_erp_record'));
    await page.fill('#inventorySearch', '없는합성검색어');
    await accountAction(() => page.click('#inventoryCoverageTab'));
    await accountAction(() => page.click('#inventoryAccountsTab'));
    assert.equal(await page.locator('#inventorySearch').inputValue(), '없는합성검색어');
    assert.equal(await page.locator('#inventoryMapping').inputValue(), 'no_erp_record');
    assert.equal(await page.locator('#inventoryRows tr[data-account]').count(), 0);
    await accountAction(() => page.click('#inventoryCoverageTab'));
    const cardReply = await accountAction(() => page.click('#inventory-stat-unknown'));
    assert.equal((await cardReply.json()).mode, 'unchanged');
    assert.equal(await page.locator('#inventoryCard').isVisible(), true, '요약 카드는 계정 분류를 자동으로 열어야 합니다');
    assert.equal(await page.locator('#inventorySearch').inputValue(), '');
    assert.ok(await page.locator('#inventoryRows tr[data-account]').count());
    checks.push('roundtrip-preserves-filters', 'summary-card-opens-accounts-and-clears-search');
    const boardReply = page.waitForResponse(response => new URL(response.url()).pathname === '/api/naver-auto/board');
    await page.click('[data-go="/naver/"]'); await settled('watch');
    const initialBoard = (await (await boardReply).json()).data;
    assert.ok(initialBoard.escalated_to_me.length >= 2, '실제 엔진이 합성 미확인 항목을 상향 판정해야 합니다');
    assert.equal(await page.locator('#upbox').isVisible(), true);
    assert.equal(await page.locator('#upbox li').first().isVisible(), false, '나에게 올라온 상세 목록은 기본 접힘이어야 합니다');
    checks.push('escalated-list-default-collapsed');
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('#upToggle').getAttribute('aria-controls'), 'upList');
    await page.focus('#upToggle'); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#upList').isVisible(), true);
    await page.evaluate(() => { window.__upToggle = document.querySelector('#upToggle'); });
    await control('correct');
    const upRefresh = await boardAction(() => page.locator('#watchReload').dispatchEvent('click'));
    assert.equal((await upRefresh.json()).mode, 'delta');
    assert.equal(await page.evaluate(() => document.activeElement === window.__upToggle), true,
      '변경분 갱신 중 상향 목록 버튼 노드와 초점을 보존해야 합니다');
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'true');
    await page.fill('#q', '없는합성검색어');
    assert.equal(await page.locator('#upbox').isVisible(), false);
    await page.fill('#q', '');
    assert.equal(await page.locator('#upList').isVisible(), true);
    assert.match(await page.locator('#upTitle').innerText(), new RegExp(initialBoard.escalated_to_me.length + '건'));
    checks.push('up-toggle-keyboard-and-delta-focus', 'up-filter-zero-restores-choice-and-count');
    await page.selectOption('#scope', 'person:101'); await settled('watch');
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'false', '담당 범위 변경은 기본 접힘으로 돌아가야 합니다');
    assert.equal(await page.locator('#upList').isVisible(), false);
    assert.match(await page.locator('#upTitle').innerText(), new RegExp(
      initialBoard.escalated_to_me.filter(row => row.possibility_id === 12).length + '건'));
    await page.selectOption('#scope', 'all'); await settled('watch');
    checks.push('scope-change-resets-up-choice');
    await page.click('#upToggle');
    const upLink = page.locator('#upList button').first();
    await upLink.click(); await page.waitForURL('**/naver/clients/*');
    await boardAction(() => page.click('[data-go="/naver/"]'));
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'true');
    await page.click('#upToggle');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => !!document.activeElement.closest('#upList')), false,
      '접힌 목록의 업체 링크는 키보드 탐색 대상에서 제외되어야 합니다');
    checks.push('up-link-navigation-and-return', 'collapsed-links-not-tabbable');
    await control('add');
    const newUpReply = await boardAction(() => page.click('#watchReload'));
    const newUp = (await newUpReply.json()).data.escalated_to_me;
    assert.equal(newUp.length, initialBoard.escalated_to_me.length + 1);
    assert.match(await page.locator('#upTitle').innerText(), new RegExp(newUp.length + '건'));
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('#upList').isVisible(), false, '새 상향 항목으로 강제 펼침하지 않습니다');
    const upHeight = await page.locator('#upbox').evaluate(node => node.getBoundingClientRect().height);
    assert.ok(upHeight < 120, '접힌 상향 목록이 오늘의 이슈를 긴 목록 아래로 밀지 않아야 합니다');
    checks.push('new-escalation-count-without-forced-expansion', 'collapsed-up-compact-layout');
    await accountAction(() => page.click('[data-go="/naver/transfers"]'));
    assert.equal(await page.locator('#inventoryCard').isVisible(), true, '메뉴 왕복은 이관 분류 선택을 유지');
    await accountAction(() => page.selectOption('#scope', 'person:101'));
    assert.equal(await page.locator('#inventoryCard').isVisible(), true, '이관 분류는 같은 로그인 범위 변경에도 유지');
    await accountAction(() => page.selectOption('#scope', 'all'));
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({width, height: 900});
      for (const panel of ['Coverage', 'Accounts']) {
        await accountAction(() => page.click('#inventory' + panel + 'Tab'));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true,
          width + 'px ' + panel + ' 분류에서 전체 페이지 가로 넘침이 없어야 합니다');
      }
    }
    await page.setViewportSize({width: 1440, height: 900});
    checks.push('both-panels-no-overflow-1440-1024-390');
    await page.route('**/api/naver-auto/accounts?**', route => route.abort('connectionfailed'), {times: 1});
    await page.click('#inventoryCoverageTab'); await settled('inventory', 'error');
    assert.equal(await page.locator('#managedCoverage').isVisible(), false);
    assert.equal(await page.locator('#inventoryCard').isVisible(), false);
    assert.ok(await page.locator('#inventoryRows tr[data-account]').count(), '숨긴 자료를 통신 실패로 공개하지 않음');
    await accountAction(() => page.locator('#inventorySync button').click());
    assert.equal(await page.locator('#managedCoverage').isVisible(), true);
    assert.doesNotMatch(await page.locator('#managedCoverage').innerText(), /아래 계정 목록/);
    assert.doesNotMatch(await page.locator('#inventory-stat-balance').innerText(), /아래 목록/);
    checks.push('transfer-selection-survives-route-and-scope', 'hidden-panel-network-failure-stays-hidden');
    let lateRelease, lateReceived, firstHeld = true;
    const lateHeld = new Promise(resolve => { lateReceived = resolve; });
    await page.route('**/api/naver-auto/accounts?**', async route => {
      const response = await route.fetch();
      if (firstHeld) { firstHeld = false; await new Promise(resolve => { lateRelease = resolve; lateReceived(); }); }
      await route.fulfill({response});
    });
    await page.click('#inventoryReload'); await lateHeld;
    await accountAction(() => page.click('#inventoryAccountsTab'));
    const lateReply = page.waitForResponse(accountsUrl);
    lateRelease(); await (await lateReply).finished();
    await page.unroute('**/api/naver-auto/accounts?**');
    assert.equal(await page.locator('#managedCoverage').isVisible(), false);
    assert.equal(await page.locator('#inventoryCard').isVisible(), true);
    checks.push('late-pre-switch-response-does-not-reopen-old-panel');
    await page.route('**/api/naver-auto/accounts?**', route => route.fulfill({status: 403, json: {error: 'org-stale'}}), {times: 1});
    await page.click('#inventoryAccountsTab'); await settled('inventory', 'error');
    assert.equal(await page.locator('#inventoryRows').innerText(), '');
    assert.equal(await page.locator('#coverageRows').innerText(), '');
    assert.equal(await page.locator('#upTitle').innerText(), '');
    assert.equal(await page.locator('#upList').innerText(), '');
    assert.equal(await page.locator('#inventoryCard').isVisible(), false);
    await accountAction(() => page.locator('#inventorySync button').click());
    checks.push('authority-failure-purges-both-panels-and-up-list');
    await boardAction(() => page.click('[data-go="/naver/"]'));
    if (await page.locator('#upToggle').getAttribute('aria-expanded') === 'false') await page.click('#upToggle');
    await page.route('**/api/naver-auto/board?**', route => route.fulfill({status: 401, json: {error: 'expired'}}), {times: 1});
    await page.click('#watchReload'); await page.waitForSelector('#s-blocked.on');
    assert.equal(await page.locator('#upList').innerText(), '');
    assert.equal(await page.locator('#inventoryAccountsTab').getAttribute('aria-pressed'), 'false',
      '로그인 종료는 이관 분류 선택도 기본값으로 초기화해야 합니다');
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'false');
    checks.push('session-end-resets-presentation-and-purges-data');
    await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({contentType: 'application/javascript',
      body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
        JSON.stringify({code: cfg.staffCode, codeVerifier: 'V'.repeat(42) + 'A'}) + ')};'}));
    await page.goto(cfg.base + '/naver/transfers'); await settled();
    assert.equal(await page.locator('#managedCoverage').isVisible(), true);
    assert.equal(await page.locator('#inventoryCard').isVisible(), false);
    assert.equal(await page.locator('#upToggle').getAttribute('aria-expanded'), 'false');
    checks.push('replacement-login-starts-with-defaults');

    await control('near-midnight');
    const midnightCtx = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
    await midnightCtx.route('**/*', route => {
      if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
      external.push(route.request().url()); return route.abort();
    });
    const midnight = await midnightCtx.newPage();
    midnight.on('pageerror', error => errors.push(error.message));
    midnight.on('request', request => {
      if (request.method() !== 'GET' && !request.url().endsWith('/session')) writes.push(request.url());
    });
    const late = new Date(cfg.now.slice(0, 10) + 'T23:59:40+09:00');
    await midnight.clock.install({time: late});
    await midnight.goto(cfg.base + '/naver/'); await settled('watch', 'current', midnight);
    await midnight.click('#upToggle');
    await midnight.click('[data-go="/naver/transfers"]'); await settled('inventory', 'current', midnight);
    await midnight.click('#inventoryAccountsTab'); await settled('inventory', 'current', midnight);
    await midnight.click('[data-go="/naver/"]'); await settled('watch', 'current', midnight);
    assert.equal(await midnight.locator('#upToggle').getAttribute('aria-expanded'), 'true');
    await control('next-day'); await midnight.clock.setSystemTime(new Date(late.getTime() + 40000));
    const nextDay = midnight.waitForResponse(boardUrl);
    await midnight.click('#watchReload'); await (await nextDay).finished(); await settled('watch', 'current', midnight);
    assert.equal(await midnight.locator('#upToggle').getAttribute('aria-expanded'), 'true',
      '날짜만 바뀌는 자료 삭제는 같은 로그인에서 선택한 펼침 상태를 바꾸지 않습니다');
    await midnight.click('[data-go="/naver/transfers"]'); await settled('inventory', 'current', midnight);
    assert.equal(await midnight.locator('#inventoryCard').isVisible(), true, '날짜 변경에도 이관 분류 선택을 유지');
    assert.deepEqual(await midnight.evaluate(() => ({local: Object.keys(localStorage), session: Object.keys(sessionStorage)})),
      {local: [], session: ['naverWatch.session']}, '분류·접힘·업체 자료는 영구 저장하지 않습니다');
    await midnightCtx.close();
    checks.push('date-only-purge-preserves-both-choices', 'no-persistent-presentation-or-company-data');
    assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(writes, []);
    console.log('view-sections-screen-ok ' + JSON.stringify({checks, errors, external, writes}));
    console.log('view-delta-screen-ok');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
