/* 실사용 손길(2026-10-05): 운영 배선과 같은 세 스위치로 실제 화면·중계·엔진을 Chromium 으로 누른다.
   열린 손길(이슈 👀 · 🔔 읽음 · 대표 점검 기준)은 화면에서 보이고 서버에 닿으며, 짝 아님·거두기·미리보기는 끝까지 닫혀 있다. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const cfg = JSON.parse(process.argv[2]);
const API = '/api/naver-auto';
const OPENED = /^\/api\/naver-auto\/(?:session|session\/refresh|issues\/[0-9]+\/(?:ack|resolve|except)|bell\/[0-9]+\/read|bell\/read-all|settings\/thresholds)$/;

async function enter(browser, code) {
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const external = [], writes = [], errors = [];
  await context.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname); });
  await page.clock.install({ time: new Date(cfg.now) });
  await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({ contentType: 'application/javascript',
    body: 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
      JSON.stringify({ code, codeVerifier: 'V'.repeat(42) + 'A' }) + ')};' }));
  await page.goto(cfg.base + '/naver/');
  await page.waitForSelector('#s-watch.on #kpis .kpi');
  const call = (method, path, body) => page.evaluate(async ([method, path, body]) => {
    const session = JSON.parse(sessionStorage.getItem('naverWatch.session'));
    const init = { method, headers: { Authorization: 'Bearer ' + session.token } };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    const response = await fetch(path, init);
    return { status: response.status, body: await response.json() };
  }, [method, API + path, body]);
  return { context, page, call, external, writes, errors };
}

(async () => {
  const browser = await chromium.launch();
  try {
    // ── 대표 ──
    const ceo = await enter(browser, cfg.ceo);
    let page = ceo.page;
    await page.waitForSelector('#issues .iss');
    assert.equal((await ceo.call('GET', '/me')).body.owner_actions, true);
    assert.equal(await page.isVisible('#verificationNotice'), true);
    const notice = await page.textContent('#verificationNotice');
    assert.ok(notice.includes('이슈는 이 화면에서 👀 확인 중 · ✅ 해결 · 🙈 예외로 처리합니다'), notice);
    assert.ok(notice.includes('자료 미확인은 0이나 정상으로 표시하지 않습니다'), notice);
    assert.ok(!notice.includes('업무 처리 기능은 열지 않습니다'), notice);

    const yellow = page.locator('#issues .iss[data-issue="' + cfg.yellow + '"]');
    await yellow.getByRole('button', { name: '👀 확인 중' }).click();
    await page.waitForFunction(id => {
      const row = document.querySelector('#issues .iss[data-issue="' + id + '"] .st');
      return row && row.classList.contains('ack');
    }, cfg.yellow);
    assert.equal(await page.locator('#issues .iss[data-issue="' + cfg.yellow + '"] .act button', { hasText: '👀 확인 중' }).count(), 0);
    const red = page.locator('#issues .iss[data-issue="' + cfg.red + '"]');
    assert.equal(await red.getByRole('button', { name: '🙈 예외…' }).count(), 1, '대표는 🔴 예외를 줄 수 있다');

    await page.click('#bell');
    await page.waitForSelector('#drawer.on .bitem');
    assert.equal(await page.isVisible('#bellAll'), true);
    const unreadBefore = (await ceo.call('GET', '/bell')).body.unread;
    assert.ok(unreadBefore >= 1, String(unreadBefore));
    await page.locator('#drawer .bitem.unread').first().click();
    await page.waitForSelector('#s-watch.on #kpis .kpi');
    await page.waitForFunction(() => !document.querySelector('#drawer.on'));
    assert.equal((await ceo.call('GET', '/bell')).body.unread, unreadBefore - 1);

    await page.click('#linksToggle');
    await page.waitForSelector('#linksBody:not([hidden]) > *');
    for (const text of ['아님', '거두기', '캠페인 이름 보기']) {
      assert.equal(await page.locator('#linksBody button', { hasText: text }).count(), 0, text);
    }

    await page.click('#menuSettings');
    await page.waitForSelector('#s-settings.on #sp-th table');
    assert.ok(!(await page.textContent('#set-ps')).includes('변경할 수 없습니다'));
    const input = page.locator('#th-zero_spend_days');
    assert.equal(await input.count(), 1);
    await input.fill(String(cfg.zeroSpendDays));
    await page.getByRole('button', { name: '기준 저장' }).click();
    await page.waitForFunction(v => {
      const el = document.querySelector('#th-zero_spend_days');
      return el && el.value === String(v) && document.querySelector('#sp-th .tl li');
    }, cfg.zeroSpendDays);
    await page.click('[data-sp="time"]');
    const time = await page.textContent('#sp-time');
    assert.ok(time.includes('알림 전송·자동입찰은 꺼져 있습니다'), time);
    assert.ok(time.includes('눌러서 읽음 처리할 수 있습니다'), time);
    assert.ok(!time.includes('비서방으로 갑니다'), time);

    for (const [path, body] of [['/links/reject', { refs: ['0'.repeat(cfg.refLength)] }],
                                ['/links/revoke', { decision_id: 1, reason: '틀림' }],
                                ['/links/preview', { ref: '0'.repeat(cfg.refLength) }]]) {
      assert.deepEqual(await ceo.call('POST', path, body), { status: 403, body: { error: 'verification-read-only' } }, path);
    }
    const ceoWrites = ceo.writes.filter(path => !OPENED.test(path) && !/\/links\/(reject|revoke|preview)$/.test(path));
    assert.deepEqual(ceoWrites, [], '화면은 열린 손길 밖으로 쓰기를 보내지 않는다');
    assert.ok(ceo.writes.includes(API + '/issues/' + cfg.yellow + '/ack'), ceo.writes.join(','));
    assert.ok(ceo.writes.some(path => /\/bell\/[0-9]+\/read$/.test(path)), ceo.writes.join(','));
    assert.ok(ceo.writes.includes(API + '/settings/thresholds'), ceo.writes.join(','));
    assert.deepEqual(ceo.external, []); assert.deepEqual(ceo.errors, []);
    await ceo.context.close();

    // ── 담당 직원(본인 담당만 · 설정 없음 · 🔴 예외는 못 줌) ──
    const staff = await enter(browser, cfg.staff);
    page = staff.page;
    await page.waitForSelector('#issues .iss');
    assert.equal(await page.isVisible('#menuSettings'), false);
    const staffRed = page.locator('#issues .iss[data-issue="' + cfg.red + '"]');
    assert.equal(await staffRed.count(), 1);
    assert.equal(await staffRed.getByRole('button', { name: '👀 확인 중' }).count(), 1);
    assert.equal(await staffRed.getByRole('button', { name: '🙈 예외…' }).count(), 0, '담당은 🔴 예외를 못 준다');
    assert.equal(await page.locator('#issues .iss[data-issue="' + cfg.yellow + '"]').count(), 0, '남의 담당 이슈는 보이지 않는다');
    const denied = await staff.call('POST', '/settings/thresholds', { changes: { zero_spend_days: 5 } });
    assert.deepEqual([denied.status, denied.body.error], [403, 'ceo-only']);
    assert.deepEqual(staff.external, []); assert.deepEqual(staff.errors, []);
    await staff.context.close();
    console.log('owner-actions-screen-ok: notice, issue-ack, bell-read, thresholds, staff-scope, links-closed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
