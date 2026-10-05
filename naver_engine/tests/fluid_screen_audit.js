/* 합성 화면 서버에서만 호출하는 중앙 브라우저 검수 helper. 서버 변경 요청은 하지 않는다. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function assertNoHorizontalOverflow(page, label) {
  const result = await page.evaluate(() => {
    const visible = element => !!element.getClientRects().length;
    const failures = [...document.querySelectorAll('.screen.on, .tblwrap, .tabs, .toc, .box, .report-history-content, .nr-table, .nr-report, .nr-quality, .nr-day-table, .nr-history-row')]
      .filter(visible).filter(element => element.scrollWidth > element.clientWidth + 1)
      .map(element => ({ id: element.id, class: element.className, scroll: element.scrollWidth, width: element.clientWidth }));
    return { viewport: document.documentElement.clientWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth,
      main: document.querySelector('main').getBoundingClientRect().width, failures };
  });
  assert.ok(result.document <= result.viewport + 1 && result.body <= result.viewport + 1,
    label + ': 문서 가로 넘침 ' + JSON.stringify(result));
  assert.deepEqual(result.failures, [], label + ': 내부 가로 넘침');
  assert.ok(result.main >= result.viewport - 1, label + ': main 화면 폭 미사용');
}

async function auditFluidScreens(page, cfg) {
  const widths = [320, 375, 768, 1024, 1440, 1920];
  // 메뉴(대표 4) · 📊 안의 하위 탭 · 메뉴에서 뺀 🤖 는 주소로만 연다(주소는 남김)
  const screens = [
    ['watch', '/naver/', '#kpis .kpi', '.top .menu'],
    ['dashboard', '/naver/dashboard', '#dashboardMetrics .dashboard-metric', '.top .menu'],
    ['reports', '/naver/reports', '#reportsStatus', '#s-dashboard.on .subtabs'],
    ['transfers', '/naver/transfers', '#inventoryRows tr', '.top .menu'],
    ['settings', '/naver/settings', '#sp-th table', '.top .menu'],
    ['automation', '/naver/automation', '#s-automation .auto-soon', null]
  ];
  assert.equal(await page.locator('.top .menu [data-go="/naver/automation"], .top .menu [data-go="/naver/reports"]').count(), 0,
    '🤖 자동화·📄 보고서는 메뉴에 없다');
  for (const [screen, route, ready, via] of screens) {
    if (via) await page.locator(via + ' [data-go="' + route + '"]').click();
    else await page.evaluate(path => { history.pushState(null, '', path); dispatchEvent(new PopStateEvent('popstate')); }, route);
    await page.locator('#s-' + screen + '.on').waitFor();
    await page.locator(ready).first().waitFor();
    if (screen === 'reports') {
      await page.waitForFunction(() => document.querySelector('#reportsStatus').textContent.includes('관리 중인 광고 계정'));
      assert.ok(await page.locator('#reportsRows .empty, #reportsRows [data-account-key]').count(), '보고서 빈 상태 또는 관리 계정 목록');
      assert.match(await page.locator('#reportsPages').innerText(), /\d+페이지/, '계정 목록 페이지 표시');
    }
    if (screen === 'watch') await page.locator('#tblChips [data-f="all"]').click();
    for (const width of widths) {
      await page.setViewportSize({ width, height: 960 });
      await assertNoHorizontalOverflow(page, screen + '-' + width);
      if (screen === 'settings') {
        for (const pane of ['ppl', 'time', 'sys', 'th']) {
          await page.locator('[data-sp="' + pane + '"]').click();
          await assertNoHorizontalOverflow(page, screen + '-' + pane + '-' + width);
        }
      }
      if (cfg.shots && [320, 1920].includes(width)) {
        await page.screenshot({ path: path.join(cfg.shots, 'fluid-' + screen + '-' + width + '.png'), fullPage: true });
      }
    }
  }
  await page.locator('.top .menu [data-go="/naver/transfers"]').click();
  const recovery = page.locator('#inventoryRows details.collection-recovery').first();
  await recovery.locator('summary').waitFor();
  if (!(await recovery.evaluate(element => element.open))) await recovery.locator('summary').click();
  const period = page.locator('#inventoryRows').getByRole('button', { name: '기간 재확인', exact: true }).first();
  await period.waitFor();
  for (const width of widths) {
    await page.setViewportSize({ width, height: 960 });
    await period.click();
    await page.locator('#m-period-recheck.on').waitFor();
    assert.equal(await page.locator('#periodStart').evaluate(element => element === document.activeElement), true);
    await assertNoHorizontalOverflow(page, 'period-dialog-' + width);
    await page.locator('#periodSave').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('#periodStart').evaluate(element => element === document.activeElement), true);
    await page.keyboard.press('Escape');
    assert.equal(await period.evaluate(element => element === document.activeElement), true);
  }
  // 긴 이름·요약·큰 수치·여러 판은 합성 GET 응답만 사용한다. 기존 API를 POST하지 않는다.
  const account = { account_key: 'fluid-account-1', ad_account_no: cfg.own, account_name: '합성_긴_광고계정명_'.repeat(16) };
  const report = { report_id: 99003, possibility_id: 11, period_key: 'monthly:2026-09-01:2026-09-30', revision_no: 3,
    company_name: '합성_긴_업체명_'.repeat(16), status: 'partial', review_status: 'needs_staff_review', can_review: true,
    generated_at: cfg.now, owner: { name: '합성_긴_담당자_'.repeat(8) }, scope: { kind: 'account', ...account },
    validation: { status: 'pending', last_attempt_at: cfg.now, last_checked_at: cfg.now, pending_account_days: 30 },
    change_summary: { previous_report_id: 99002, changed_metrics: ['spend', 'conversions'], metric_deltas: { spend: -1234567890123, conversions: 0 },
      changed_days: Array.from({ length: 30 }, (_, i) => '2026-09-' + String(i + 1).padStart(2, '0')), completeness_changed: true },
    payload: { format_version: 2, period: { kind: 'monthly', start: '2026-09-01', end: '2026-09-30' },
      totals: { spend: 9999999999999, impressions: 9876543210987, clicks: 123456789, conversions: null },
      ratios: { ctr: 12.3456, cpc: 1234567, roas: null },
      coverage: { basic_complete: true, conversion_complete: false, expected_account_days: 30, basic_complete_account_days: 30, conversion_complete_account_days: 27 },
      details: { status: 'available', briefing: ['합성_긴_성과요약_'.repeat(60)],
        daily: Array.from({ length: 30 }, (_, i) => ({ day: '2026-09-' + String(i + 1).padStart(2, '0'), status: 'partial',
          totals: { spend: 333333333333, impressions: 329218107, clicks: 4115226, conversions: null }, ratios: {},
          coverage: { basic_complete: true, conversion_complete: false } })),
        comparison: { period: { kind: 'monthly', start: '2026-08-01', end: '2026-08-31' }, status: 'insufficient_data',
          basic_status: 'insufficient_data', conversion_status: 'insufficient_data', totals: {}, ratios: {}, changes: {} },
        management_records: [], next_actions: [] },
      missing: [{ day: '2026-09-30', account_index: 1, reason: '원천_사유_'.repeat(80), metrics: ['conversion_value', 'conversions'] }] } };
  const prior = { ...report, report_id: 99002, revision_no: 2, change_summary: null,
    payload: { ...report.payload, totals: { ...report.payload.totals, spend: 8888888888888 } } };
  const listRow = { ...account, report_id: report.report_id, possibility_id: report.possibility_id,
    company_name: report.company_name, owner: report.owner, workflow: '진행중', status: report.status, generated_at: cfg.now };
  const reportsPattern = '**/api/naver-auto/reports/accounts?*', detailPattern = '**/api/naver-auto/reports/detail?*',
    historyPattern = '**/api/naver-auto/reports/history?*';
  const detailReads = [];
  await page.route(reportsPattern, route => {
    assert.equal(route.request().method(), 'GET');
    const monthly = new URL(route.request().url()).searchParams.get('kind') === 'monthly';
    return route.fulfill({ json: { rows: monthly ? [listRow] : [], total: monthly ? 1 : 0, page: 0, next_page: null,
      period: monthly ? report.payload.period : { kind: 'weekly', start: '2026-09-21', end: '2026-09-27' } } });
  });
  await page.route(detailPattern, route => {
    assert.equal(route.request().method(), 'GET');
    const params = new URL(route.request().url()).searchParams, id = Number(params.get('report_id'));
    assert.equal(params.get('account_key'), account.account_key, '현재 판과 이전 판 모두 선택 계정 범위를 유지');
    assert.ok([report.report_id, prior.report_id].includes(id), '등록된 합성 판만 조회');
    detailReads.push(id);
    return route.fulfill({ json: id === report.report_id ? report : prior });
  });
  await page.route(historyPattern, route => {
    assert.equal(route.request().method(), 'GET');
    const params = new URL(route.request().url()).searchParams;
    assert.equal(params.get('possibility_id'), '11');
    assert.equal(params.get('period_key'), report.period_key);
    return route.fulfill({ json: { items: [prior], next_before_report_id: null } });
  });
  try {
    await page.locator('.top .menu [data-go="/naver/dashboard"]').click();
    await page.locator('#s-dashboard.on .subtabs [data-go="/naver/reports"]').click();
    await page.locator('#reportMonthly').click();
    await page.locator('[data-report="99003"]').waitFor();
    for (const width of widths) {
      await page.setViewportSize({ width, height: 960 });
      await assertNoHorizontalOverflow(page, 'report-long-account-list-' + width);
    }
    await page.locator('[data-report="99003"]').getByRole('button', { name: /보고서 보기$/ }).click();
    const current = page.locator('#reportDetail');
    await current.locator('#reportDetailTitle').waitFor();
    assert.match(await current.locator('.report-meta').first().innerText(), /저장된 3판/);
    assert.match(await current.locator('[data-metric="spend"] dd').innerText(), /9,999,999,999,999원/);
    await current.locator('.nr-quality>summary').click();
    await current.locator('.report-history>summary').click();
    await current.locator('.nr-history-row').getByRole('button', { name: '이 판 보기', exact: true }).waitFor();
    assert.match(await current.locator('.nr-history-row').innerText(), /2판/);
    await current.locator('.report-missing>summary').first().click();
    await current.locator('.nr-day-table>summary').click();
    assert.equal(await current.locator('.nr-day-table tbody tr').count(), 30, '월간 일별 숫자 30일 유지');
    assert.match(await current.locator('.report-missing').innerText(), /2026-09-30.*전환 매출.*전환/);
    assert.equal((await current.innerText()).includes('원천_사유_'), false, '내부 원천 사유는 화면에 노출하지 않음');
    assert.match(await current.locator('.report-changes').innerText(), /-1,234,567,890,123원/);
    assert.equal(await current.getByRole('button', { name: '검토 승인', exact: true }).count(), 0);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 960 });
      await assertNoHorizontalOverflow(page, 'report-long-history-' + width);
    }
    await current.locator('.nr-history-row').getByRole('button', { name: '이 판 보기', exact: true }).click();
    await page.waitForFunction(() => {
      const meta = document.querySelector('#reportDetail .report-meta');
      return meta && meta.textContent.includes('저장된 2판');
    });
    assert.match(await current.locator('[data-metric="spend"] dd').innerText(), /8,888,888,888,888원/, '이전 판은 당시 저장된 숫자로 열림');
    assert.equal(await current.getByRole('button', { name: '검토 승인', exact: true }).count(), 0);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 960 });
      await assertNoHorizontalOverflow(page, 'report-prior-edition-' + width);
    }
    assert.deepEqual(detailReads, [99003, 99002], '현재 판과 선택한 이전 판만 GET 조회');
  } finally {
    await page.unroute(reportsPattern); await page.unroute(detailPattern); await page.unroute(historyPattern);
  }
  await page.setViewportSize({ width: 1280, height: 960 });
}

module.exports = { auditFluidScreens, assertNoHorizontalOverflow };
