'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
  // 개편(2026-10-06): 「전체 광고주 보기」는 접혀서 시작한다 — 표를 다루는 이 시험은 펼친 채로 본다
  await ctx.addInitScript(() => document.addEventListener('DOMContentLoaded', () => { const d = document.getElementById('allFold'); if (d) d.open = true; }));
  const page = await ctx.newPage(), errors = [], external = [], writes = [];
  await ctx.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({contentType: 'application/javascript',
    body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
      JSON.stringify({code: cfg.code, codeVerifier: 'V'.repeat(42) + 'A'}) + ')};'}));
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', request => {
    if (request.method() !== 'GET' && !request.url().endsWith('/session')) writes.push(request.url());
  });
  const snapshot = {
    selection: 'all', ready: true, period: {start: '2026-09-01', end: '2026-09-28', days: 28, timezone: 'Asia/Seoul'},
    accounts: {total: 4, matched: 3, unmatched: 1, unclassified: 0},
    advertisers: {total: 2, complete: 1, unknown: 1},
    coverage: {complete_accounts: 2, pending_accounts: 1, partial_accounts: 0, retry_accounts: 1, limited_accounts: 0,
      oldest_collected_at: cfg.now, newest_collected_at: cfg.now},
    totals: {impressions: 1200, clicks: 30, spend: 12345.99, conversion_value: 15000},
    averages: {advertiser_impressions: 600, advertiser_clicks: 15, advertiser_daily_spend: 100.9, daily_spend: 440.9},
    ratios: {ctr: 2.5, cpc: 411.53, roas: 250, roas_accounts: 1, roas_spend: 6000, roas_conversion_value: 15000},
    delivery: {active: 1, inactive: 1, unknown: 2}, configuration: {enabled: 3, disabled: 0, unknown: 1},
    accounts_at: cfg.now, catalog_at: cfg.now, catalog_status: 'accepted'
  };
  let dashboard = snapshot, failDashboard = false, holdMine = false, releaseMine, mineStarted = false;
  let dashboardFailure = 'engine-unavailable';
  let holdNextDashboard = false, dashboardStarted, releaseDashboard, dashboardRequests = 0;
  await page.route('**/api/naver-auto/dashboard?**', async route => {
    dashboardRequests++;
    const selection = new URL(route.request().url()).searchParams.get('selection');
    const response = JSON.parse(JSON.stringify(dashboard));
    const fail = failDashboard;
    response.selection = selection;
    if (holdNextDashboard) {
      holdNextDashboard = false;
      await new Promise(resolve => { releaseDashboard = resolve; dashboardStarted(); });
    }
    if (holdMine && selection === 'me') {
      mineStarted = true;
      response.totals.spend = 777777;
      await new Promise(resolve => { releaseMine = resolve; });
    }
    if (fail) return route.fulfill({status: 503, json: {error: dashboardFailure}});
    await route.fulfill({json: response});
  });
  let board;
  await page.route('**/api/naver-auto/board?**', async route => {
    const response = await route.fetch();
    const envelope = await response.json();
    // 이 시험은 관제 필터용 fixture를 꾸민다. 제품 변경분 응답의 full 본문을 먼저 푼다.
    const data = envelope.mode === 'full' ? envelope.data : envelope;
    const colors = ['red', 'yellow', 'green', 'white'];
    data.rows.forEach((row, i) => {
      row.verdict = {...row.verdict, color: colors[i], needs_attention: i < 2};
      row.name = '합성 광고주 ' + row.possibility_id;
    });
    const issue = data.issue_rows[0];
    data.issue_rows = data.rows.map((row, i) => ({...issue, possibility_id: row.possibility_id,
      name: row.name, issue_id: 100 + i, severity: 'red', state_now: 'new'}));
    data.done_rows = data.rows.map((row, i) => ({...data.issue_rows[i], issue_id: 200 + i,
      state_now: 'resolved'}));
    data.escalated_to_me = data.rows.map(row => ({possibility_id: row.possibility_id,
      name: row.name, code: 'BIZMONEY_LOW', waited_hours: 13}));
    data.escalated_to_me.push({possibility_id: 999, name: '선택 범위 밖 상향', code: 'BIZMONEY_LOW', waited_hours: 20});
    data.counts = {total: data.rows.length, needs_attention: 2, red: 1, yellow: 1, green: 1, white: 1};
    board = data;
    await route.fulfill({response, json: data});
  });
  try {
    await page.clock.install({time: new Date(cfg.now)});
    await page.goto(cfg.base + '/naver/');
    await page.waitForSelector('#s-watch.on #kpis .kpi');
    assert.equal(await page.locator('#kpis .kpi').count(), 4, '개편 숫자 4칸(오늘 볼 곳 · 문제없음 · 연결 안 됨 · 점검 못 함)');
    await page.click('#doneToggle');
    async function assertSelection(filter, query = '') {
      const expected = board.rows.filter(row => (!query || row.name.includes(query)) &&
        (filter === 'all' || (filter === 'need' ? row.verdict.needs_attention : row.verdict.color === filter)));
      const ids = expected.map(row => row.possibility_id).sort();
      assert.deepEqual((await page.locator('#tbody tr[data-pid]').evaluateAll(rows => rows.map(row => Number(row.dataset.pid)))).sort(), ids);
      // 개편(2026-10-06): 오늘 볼 광고주 · 오늘 풀린 것 · 올림 목록은 표 거르기·찾기와 상관없이 고른 범위 전부(서버 그대로)
      const open = board.rows.map((row, i) => 100 + i).sort();
      const done = board.rows.map((row, i) => 200 + i).sort();
      assert.deepEqual((await page.locator('#issues [data-issue]').evaluateAll(rows => rows.map(row => Number(row.dataset.issue)))).sort(), open);
      assert.deepEqual((await page.locator('#doneList [data-issue]').evaluateAll(rows => rows.map(row => Number(row.dataset.issue)))).sort(), done);
      assert.deepEqual((await page.locator('#upbox li button').allTextContents()).sort(), board.rows.map(row => row.name).sort());
      assert.doesNotMatch(await page.textContent('#upbox'), /선택 범위 밖 상향/, '고른 범위의 광고주가 아닌 올림은 보이지 않는다');
    }
    // 숫자 칸(문제없음 · 연결 안 됨 · 점검 못 함)을 누르면 전체 광고주 표가 서버 today_group 으로 걸러진다
    async function assertGroup(group) {
      const want = board.rows.filter(row => row.today_group === group).map(row => row.possibility_id).sort();
      assert.deepEqual((await page.locator('#tbody tr[data-pid]').evaluateAll(rows => rows.map(row => Number(row.dataset.pid)))).sort(), want);
    }
    for (const [cls, group] of [['okk', 'ok'], ['cut', 'unlinked'], ['nil', 'unchecked']]) {
      await page.click('#kpis .kpi.' + cls);
      assert.equal(await page.getAttribute('#kpis .kpi.' + cls, 'aria-pressed'), 'true');
      assert.equal(await page.locator('#allFold').evaluate(d => d.open), true);
      await assertGroup(group);
    }
    await page.focus('#kpis .kpi.cut');
    await page.keyboard.press('Enter');
    await assertGroup('unlinked');
    assert.equal(await page.getAttribute('#kpis .kpi.cut', 'aria-pressed'), 'true');
    assert.equal(await page.getAttribute('#kpis .kpi.need', 'aria-pressed'), null, '오늘 볼 곳은 거르기가 아니라 아래 목록으로 가는 단추');
    for (const filter of ['all', 'need', 'red', 'yellow', 'green', 'white']) {
      await page.click('#tblChips [data-f="' + filter + '"]');
      await assertSelection(filter);
    }
    await page.click('#tblChips [data-f="all"]');
    await page.fill('#q', board.rows[0].name);
    await assertSelection('all', board.rows[0].name);
    await page.fill('#q', '없는 광고주');
    await assertSelection('all', '없는 광고주');
    assert.equal(await page.locator('#upbox').isVisible(), false);
    const menu = await page.locator('.menu button').allTextContents();
    assert.equal(menu.findIndex(t => t.includes('관제')), 0);
    assert.equal(menu.findIndex(t => t.includes('성과·보고서')), 1);
    await page.focus('.top .menu [data-go="/naver/dashboard"]');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#s-dashboard.on [data-status="partial"]');
    assert.equal(new URL(page.url()).pathname, '/naver/dashboard');
    assert.equal(await page.locator('#dashboardMetrics .dashboard-metric').count(), 8);
    assert.match(await page.textContent('#dashboardCoverage'), /확인 2 \/ 4계정/);
    assert.equal(await page.textContent('#dashboard-spend .value'), '12,345원');
    assert.equal(await page.textContent('#dashboard-roas .value'), '250%');
    assert.match(await page.textContent('#dashboardRatioNote'), /1계정.*6,000원.*15,000원/);
    assert.match(await page.textContent('#dashboardDelivery'), /어제 집행 확인.*1.*어제 실적 없음.*1.*미확인.*2/);
    assert.match(await page.textContent('#dashboardConfiguration'), /설정상 운영 가능.*3.*운영 가능 캠페인 없음.*0.*설정 미확인.*1/);
    assert.match(await page.textContent('#dashboardDeliveryNote'), /설정 중지.*뜻하지 않/);
    await page.evaluate(() => window.scrollTo(0, 0));
    assert.equal(await page.evaluate(() => window.scrollY), 0, '전체 화면 캡처는 문서 맨 위에서 시작한다');
    if (cfg.shots) await page.screenshot({path: path.join(cfg.shots, 'dashboard-desktop.png'), fullPage: true});
    failDashboard = true;
    await page.evaluate(() => { window.__dashboardBeforeFailure = document.querySelector('#dashboard-spend'); });
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardSync[data-status="stale"]');
    assert.equal(await page.textContent('#dashboard-spend .value'), '12,345원', '같은 범위의 일시적 실패에는 이전 확인값을 유지한다');
    assert.equal(await page.textContent('#dashboard-roas .value'), '250%');
    assert.equal(await page.evaluate(() => window.__dashboardBeforeFailure === document.querySelector('#dashboard-spend')), true);
    assert.equal(await page.locator('#dashboardMetrics').isVisible(), true);
    assert.match(await page.textContent('#dashboardSync'), /최신화 실패.*이전 확인 자료.*서버 변경 확인 시각/);
    failDashboard = false;
    dashboard = {...snapshot, accounts: {...snapshot.accounts, total: 0}, coverage: {...snapshot.coverage, complete_accounts: 0}};
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="empty"]');
    assert.equal(await page.textContent('#dashboard-spend .value'), '—');
    dashboard = {...snapshot, period: {start: '2026-10-01', end: '2026-09-30', days: 0, timezone: 'Asia/Seoul'}};
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="no-period"]');
    assert.equal(await page.textContent('#dashboard-spend .value'), '—');
    assert.match(await page.textContent('#dashboardPeriod'), /집계 기간.*없/);
    dashboard = {...snapshot, coverage: {...snapshot.coverage, complete_accounts: 0, pending_accounts: 4, retry_accounts: 0}};
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="collecting"]');
    assert.equal(await page.textContent('#dashboard-spend .value'), '—');
    dashboard = {...snapshot, coverage: {...snapshot.coverage, complete_accounts: 0, pending_accounts: 3, retry_accounts: 1}};
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="failed"]');
    dashboard = {...snapshot, ready: false};
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="unavailable"]');
    assert.equal(await page.textContent('#dashboard-spend .value'), '—');
    dashboard = {...snapshot, ratios: {...snapshot.ratios, roas: null, roas_accounts: 0, roas_spend: null, roas_conversion_value: null}};
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="partial"]');
    assert.equal(await page.textContent('#dashboard-roas .value'), '—');
    dashboard = snapshot;
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardStatus[data-status="partial"]');
    holdMine = true;
    await page.selectOption('#scope', 'me');
    await page.waitForSelector('#dashboardSync[data-status="checking"]');
    assert.equal(await page.locator('#dashboard-spend').count(), 0, '범위를 바꾸면 옛 숫자 노드를 즉시 삭제한다');
    assert.equal(await page.locator('#s-dashboard.view-unverified').count(), 1);
    assert.equal(await page.locator('#dashboardMetrics').isVisible(), false, '새 범위 권한 확인 전에는 지표를 숨긴다');
    const deadline = Date.now() + 5000;
    while (!mineStarted && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(mineStarted, '느린 담당 범위 요청이 시작됨');
    await page.selectOption('#scope', 'all');
    await page.waitForSelector('#dashboardStatus[data-status="partial"]');
    const late = page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.pathname === '/api/naver-auto/dashboard' && url.searchParams.get('selection') === 'me';
    });
    releaseMine();
    await late;
    await page.waitForTimeout(100);
    assert.equal(await page.textContent('#dashboard-spend .value'), '12,345원', '늦게 온 이전 담당 범위의 응답은 버린다');
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.evaluate(() => window.scrollTo(0, 0));
    if (cfg.shots) await page.screenshot({path: path.join(cfg.shots, 'dashboard-mobile.png'), fullPage: true});
    // 조직 권한 오류는 일반 통신 실패와 달리 현재·숨겨진 업체 자료를 모두 삭제한다.
    dashboardFailure = 'org-stale'; failDashboard = true;
    await page.click('#dashboardReload');
    await page.waitForSelector('#dashboardSync[data-status="error"]');
    assert.equal(await page.locator('#s-dashboard.view-unverified').count(), 1);
    assert.equal(await page.locator('#dashboardMetrics').isVisible(), false);
    assert.equal(await page.locator('#dashboardMetrics .dashboard-metric').count(), 0);
    assert.equal(await page.locator('#tbody tr[data-pid]').count(), 0, '숨겨진 관제 업체 행도 권한 오류에 삭제한다');
    assert.equal(await page.locator('#s-dashboard .subtabs [data-go="/naver/reports"]').isVisible(), true,
      '자료를 확인하지 못해도 제목·하위 탭은 남아 광고주별 보고서로 옮겨 갈 수 있다');
    assert.doesNotMatch(await page.textContent('#s-dashboard'), /12,345원|250%/);
    assert.match(await page.textContent('#dashboardSync'), /현재 권한·조직 자료를 확인할 수 없습니다/);
    dashboardFailure = 'engine-unavailable'; failDashboard = false;
    await page.locator('#dashboardSync button').click();
    await page.waitForSelector('#dashboardSync[data-status="current"]');
    assert.equal(await page.textContent('#dashboard-spend .value'), '12,345원');
    // 자정 전 요청을 일부러 보류한다. 이전 달 응답은 그리지 않고 새 날짜 자료를 다시 요청해야 한다.
    const firstOfMonth = {...snapshot, period: {start: '2026-10-01', end: '2026-09-30', days: 0, timezone: 'Asia/Seoul'}};
    async function crossMidnight(failAfter) {
      await page.clock.setSystemTime(new Date('2026-09-30T23:59:59+09:00'));
      dashboard = {...snapshot, period: {start: '2026-09-01', end: '2026-09-29', days: 29, timezone: 'Asia/Seoul'},
        totals: {...snapshot.totals, spend: 111111}};
      failDashboard = false;
      holdNextDashboard = true;
      const before = dashboardRequests;
      const started = new Promise(resolve => { dashboardStarted = resolve; });
      await page.click('#dashboardReload');
      await started;
      assert.equal(await page.locator('#dashboard-spend').count(), 0, '날짜 변경 시 전 날짜 자료 노드를 삭제한다');
      assert.equal(await page.locator('#s-dashboard.view-unverified').count(), 1);
      assert.equal(await page.locator('#dashboardMetrics').isVisible(), false);
      await page.clock.setSystemTime(new Date('2026-10-01T00:00:01+09:00'));
      dashboard = firstOfMonth;
      failDashboard = failAfter;
      releaseDashboard();
      await page.waitForSelector(failAfter ? '#dashboardSync[data-status="error"]' : '#dashboardStatus[data-status="no-period"]');
      assert.equal(dashboardRequests, before + 2, '날짜가 바뀐 응답을 버리고 새 날짜로 한 번 재조회한다');
      if (failAfter) {
        assert.equal(await page.locator('#dashboard-spend').count(), 0);
        assert.equal(await page.locator('#s-dashboard.view-unverified').count(), 1);
        assert.equal(await page.locator('#dashboardMetrics').isVisible(), false, '새 날짜 조회 실패에 이전 달 실적을 다시 표시하지 않는다');
      } else {
        assert.equal(await page.textContent('#dashboard-spend .value'), '—');
        assert.equal(await page.locator('#s-dashboard.view-unverified').count(), 0);
      }
      assert.doesNotMatch(await page.textContent('#s-dashboard'), /111,111원|12,345원|2026-09-29/);
      if (!failAfter) assert.match(await page.textContent('#dashboardPeriod'), /이번 달 집계 기간 없음/);
    }
    await crossMidnight(false);
    await crossMidnight(true);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.deepEqual(writes, [], '필터·대시보드·새로고침은 업무 변경 요청을 보내지 않는다');
    console.log('dashboard-screen-ok');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
