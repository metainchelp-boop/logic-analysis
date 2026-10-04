/* 합성 화면 서버에서만 호출하는 중앙 브라우저 검수 helper. 서버 변경 요청은 하지 않는다. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function assertNoHorizontalOverflow(page, label) {
  const result = await page.evaluate(() => {
    const visible = element => !!element.getClientRects().length;
    const failures = [...document.querySelectorAll('.screen.on, .tblwrap, .tabs, .toc, .box, .report-history-content')]
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
  const screens = [
    ['dashboard', '/naver/dashboard', '#dashboardMetrics .dashboard-metric'],
    ['watch', '/naver/', '#kpis .kpi'],
    ['automation', '/naver/automation', '#s-automation .auto-soon'],
    ['reports', '/naver/reports', '#reportsStatus'],
    ['transfers', '/naver/transfers', '#inventoryRows tr'],
    ['settings', '/naver/settings', '#sp-th table']
  ];
  for (const [screen, route, ready] of screens) {
    await page.locator('.top .menu [data-go="' + route + '"]').click();
    await page.locator('#s-' + screen + '.on').waitFor();
    await page.locator(ready).first().waitFor();
    if (screen === 'reports') {
      await page.waitForFunction(() => document.querySelector('#reportsStatus').textContent.includes('페이지'));
      assert.ok(await page.locator('#reportsRows .empty, #reportsRows .report-card').count(), '보고서 빈 상태 또는 판 목록');
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
  // 긴 사유·큰 수치·여러 판은 합성 GET 응답만 사용한다. 기존 API를 POST하지 않는다.
  const report = { report_id: 99003, possibility_id: 11, period_key: 'monthly:2026-09-01:2026-09-30', revision_no: 3,
    company_name: '합성_긴_업체명_'.repeat(16), status: 'ready', review_status: 'needs_staff_review', can_review: true,
    generated_at: cfg.now, owner: { name: '합성 담당자' },
    validation: { status: 'pending', last_attempt_at: cfg.now, last_checked_at: cfg.now, pending_account_days: 30 },
    change_summary: { previous_report_id: 99002, changed_metrics: ['spend', 'conversions'], metric_deltas: { spend: -1234567890123, conversions: 0 },
      changed_days: Array.from({ length: 30 }, (_, i) => '2026-09-' + String(i + 1).padStart(2, '0')), completeness_changed: true },
    payload: { period: { kind: 'monthly', start: '2026-09-01', end: '2026-09-30' },
      totals: { spend: 9999999999999, impressions: 9876543210987, clicks: 123456789, conversions: null },
      ratios: { ctr: 12.3456, cpc: 1234567, roas: null },
      coverage: { basic_complete: true, expected_account_days: 300, basic_complete_account_days: 300, conversion_complete_account_days: 270 },
      missing: [{ day: '2026-09-30', account_index: 1, reason: '원천_사유_'.repeat(80), metrics: ['conversion_value', 'conversions'] }] } };
  const reportsPattern = '**/api/naver-auto/reports?*', historyPattern = '**/api/naver-auto/reports/history?*';
  await page.route(reportsPattern, route => route.fulfill({ json: { rows: [report] } }));
  await page.route(historyPattern, route => route.fulfill({ json: { items: [{ ...report, report_id: 99002, revision_no: 2 }], next_before_report_id: null } }));
  try {
    await page.locator('.top .menu [data-go="/naver/reports"]').click();
    await page.locator('[data-report="99003"]').waitFor();
    const current = page.locator('[data-report="99003"]');
    await current.locator('.report-history>summary').click();
    await page.locator('[data-report="99002"]').waitFor();
    await current.locator('.report-missing>summary').first().click();
    assert.equal(await current.getByRole('button', { name: '검토 승인', exact: true }).count(), 0);
    assert.equal(await page.locator('[data-report="99002"] button').count(), 0);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 960 });
      await assertNoHorizontalOverflow(page, 'report-long-history-' + width);
    }
  } finally {
    await page.unroute(reportsPattern); await page.unroute(historyPattern);
  }
  await page.setViewportSize({ width: 1280, height: 960 });
}

module.exports = { auditFluidScreens, assertNoHorizontalOverflow };
