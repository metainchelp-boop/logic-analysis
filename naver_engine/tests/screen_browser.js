/* S13 화면 시험 — 진짜 Chromium 으로 /naver/ 를 열고 누른다(``test_screen.py`` 가 띄운다 · 네트워크 0).
 *
 * 앞(시험 서버) = 화면 파일(③ 입구와 같은 규칙) + ③ 중계(``app.naver_relay``) → 진짜 엔진 화면 API(가짜 ① · 가짜 저장소).
 * 결과는 표준 출력에 JSON 한 줄: [{name, pass, detail}] — 파이썬 시험이 하나씩 대조한다. 예시 번호·이름은 지어낸 것.
 */
'use strict';
const { chromium } = require('playwright');

const cfg = JSON.parse(process.argv[2]);
const base = cfg.base;
const results = [];
async function shot(p, name) { if (cfg.shots) await p.screenshot({ path: cfg.shots + '/' + name + '.png', fullPage: true }); }
function ok(name, pass, detail) { results.push({ name, pass: !!pass, detail: detail === undefined ? null : detail }); }

async function newCtx(browser, opts) {
  const ctx = await browser.newContext(Object.assign({ locale: 'ko-KR', timezoneId: 'Asia/Seoul' }, opts && opts.context || {}));
  const log = { requests: [], external: [], csp: [], errors: [], statuses: [] };
  await ctx.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith(base + '/')) return route.continue();
    log.external.push(u);
    return route.abort();
  });
  // 개편(2026-10-06): 「전체 광고주 보기」는 접혀서 시작한다 — 표를 다루는 이 시험은 펼친 채로 본다(접힘·숫자 칸 누르기는 아래 「가짜 값」에서 본다)
  if (!(opts && opts.foldClosed)) {
    await ctx.addInitScript(() => document.addEventListener('DOMContentLoaded', () => { const d = document.getElementById('allFold'); if (d) d.open = true; }));
  }
  await ctx.addInitScript(() => {
    window.__csp = [];
    document.addEventListener('securitypolicyviolation', (e) => { window.__csp.push(e.violatedDirective + ' ' + e.blockedURI); });
  });
  ctx.on('request', (r) => log.requests.push({ url: r.url(), method: r.method(), referer: r.headers()['referer'] || null,
                                                nav: r.isNavigationRequest() }));
  ctx.on('response', (r) => log.statuses.push([r.status(), r.url().replace(base, '')]));
  return { ctx, log };
}
async function page(ctx, log) {
  const p = await ctx.newPage();
  p.on('pageerror', (e) => log.errors.push(String(e.message || e)));
  // 브라우저가 스스로 적는 「Failed to load resource」(4xx 응답)는 화면 오류가 아니다 — 응답 상태는 따로 본다
  p.on('console', (m) => { if (m.type() === 'error' && !/^Failed to load resource/.test(m.text())) log.errors.push(m.text()); });
  return p;
}
// S13 화면 회귀는 로그인 교환 완료 seam에 합성 결과를 주입한다.
// S16의 실제 opener/PKCE 수신부는 별도 보안 브라우저/VM 시험에서 검증한다.
async function enter(p, url, code) {
  const pattern = '**/naver/sso-bootstrap.js';
  await p.route(pattern, route => route.fulfill({contentType:'application/javascript',
    body: 'window.__metaincSso={started:true,legacyPresent:false,consume:function(){return Promise.resolve(' +
      JSON.stringify({code,codeVerifier:'V'.repeat(42)+'A'}) + ');}};'}));
  try { await p.goto(url); } finally { await p.unroute(pattern); }
}
async function api(p, path, method, body) {
  return p.evaluate(async ([path, method, body]) => {
    const s = JSON.parse(sessionStorage.getItem('naverWatch.session') || 'null');
    const init = { method: method || 'GET', headers: { Authorization: 'Bearer ' + (s && s.token) } };
    if (body) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    const r = await fetch('/api/naver-auto' + path, init);
    return { status: r.status, body: await r.json() };
  }, [path, method, body]);
}
function fmt(n) { return Number(n).toLocaleString('ko-KR'); }
async function control(what) {
  const r = await fetch(base + '/__test__/' + what, { method: 'POST' });
  return r.status;
}
async function hygiene(tag, p, log, firstNavUrl) {
  ok(tag + ': 주소창에 sso 가 없다', !/sso/i.test(p.url()), p.url());
  const later = log.requests.filter((r) => r.url !== firstNavUrl);
  ok(tag + ': 뒤 요청 어디에도 sso 가 없다', later.every((r) => !/sso=/i.test(r.url)), later.filter((r) => /sso=/i.test(r.url)).map((r) => r.url));
  ok(tag + ': Referer 머리가 한 번도 안 나갔다', log.requests.every((r) => !r.referer), log.requests.filter((r) => r.referer).map((r) => r.url));
  ok(tag + ': 바깥 주소 요청 0', log.external.length === 0, log.external);
  const csp = await p.evaluate(() => window.__csp || []);
  ok(tag + ': 보안 정책(CSP) 위반 0', csp.length === 0, csp);
  ok(tag + ': 화면 오류 0', log.errors.length === 0, log.errors);
  const bad = log.statuses.filter((x) => x[0] >= 500 || (x[0] >= 400 && ![401, 404].includes(x[0])));
  ok(tag + ': 뜻밖의 오류 응답 0(401 · 없는 파일 404 밖)', bad.length === 0, bad);
  const miss = log.statuses.filter((x) => x[0] === 404);
  ok(tag + ': 화면 파일은 모두 있다(404 0)', miss.length === 0, miss);
  const ls = await p.evaluate(() => { try { return localStorage.length; } catch (e) { return -1; } });
  ok(tag + ': 오래 두는 저장소를 쓰지 않는다', ls === 0, ls);
}

(async () => {
  const browser = await chromium.launch();
  try {
    // ── 대표(0) — 관제 판 · 색 = 서버 판정 · 광고주 한 장 · 설정 · 🔔 · 50분 갱신 · 좁은 화면 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      await p.clock.install();
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.ceo);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      await p.waitForSelector('#issues .iss');
      await shot(p, '1-대표-관제');
      const sess = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session') || 'null'));
      ok('대표: 자체 토큰이 sessionStorage 「naverWatch.session」에', sess && typeof sess.token === 'string' && sess.token.startsWith('v1.'));
      ok('대표: sso 원문은 저장소 어디에도 없다', !JSON.stringify(sess).includes(cfg.sso.ceo));
      const board = (await api(p, '/board?selection=all&attention=0')).body;
      const kv = await p.$$eval('#kpis .kpi .v', (els) => els.map((e) => e.textContent));
      const c = board.counts;
      const tc = board.today_counts;
      ok('대표: 숫자 4칸 = 서버 숫자(오늘 볼 곳 · 문제없음 · 연결 안 됨 · 점검 못 함)', JSON.stringify(kv) === JSON.stringify([tc.need, tc.ok, tc.unlinked, tc.unchecked].map(fmt)), kv);
      ok('대표: 숫자 4칸은 서로 겹치지 않고 더하면 전체', tc.need + tc.ok + tc.unlinked + tc.unchecked === c.total, [tc, c.total]);
      await p.click('#tblChips .chip[data-f="all"]');
      const drawn = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => [Number(e.getAttribute('data-pid')), e.getAttribute('data-color'), e.querySelector('.sig').className]));
      const want = board.rows.map((r) => [r.possibility_id, r.verdict.color, 'sig ' + r.verdict.color]).sort((a, b) => a[0] - b[0]);
      ok('대표: 표의 색 = 서버 판정(한 줄씩)', JSON.stringify(drawn.slice().sort((a, b) => a[0] - b[0])) === JSON.stringify(want), { drawn, want });
      const iss = await p.$$eval('#issues .iss', (els) => els.map((e) => Number(e.getAttribute('data-issue'))));
      ok('대표: 오늘 볼 광고주의 이슈 줄 = 서버 이슈 줄(광고주마다 묶음)', JSON.stringify(iss.slice().sort((a, b) => a - b)) === JSON.stringify(board.issue_rows.map((r) => r.issue_id).sort((a, b) => a - b)), { iss });
      const advs = await p.$$eval('#issues .adv', (els) => els.map((e) => Number(e.getAttribute('data-pid'))));
      const lookPids = board.rows.filter((r) => r.look_today).map((r) => r.possibility_id);
      ok('대표: 오늘 볼 광고주 = 서버가 「오늘 볼 곳」이라 한 광고주(+ 열린 이슈가 있는 곳)', lookPids.every((x) => advs.includes(x)) &&
        advs.every((x) => lookPids.includes(x) || board.issue_rows.some((r) => r.possibility_id === x)) && lookPids.length === tc.need, { advs, lookPids });
      const need = await p.$$eval('#kpis .kpi', (els) => els.length);
      ok('대표: 숫자 칸 4개', need === 4, need);
      ok('대표: 사람별 처리 현황(대표만)', await p.isVisible('#peopleCard') && (await p.$$eval('#people tr', (els) => els.length)) === board.people_summary.length);
      const iw = await p.textContent('#iwan');
      ok('대표: 이관 띠에 서버 이관 수', iw.includes('이관됨 ' + fmt(board.links.listed)) && iw.includes('이관 안 된 번호 ' + fmt(board.links.unlinked_numbers)), iw);
      await p.click('#iwan .ichip:has-text("이관 안 된 번호")');
      const nl = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => Number(e.getAttribute('data-pid'))));
      const unl = (await api(p, '/unlinked')).body.rows.map((r) => r.possibility_id);
      ok('대표: 「이관 안 된 번호」를 누르면 월요일 알림(/unlinked)과 같은 광고주', JSON.stringify(nl) === JSON.stringify(board.rows.filter((r) => r.unlinked).map((r) => r.possibility_id)) && JSON.stringify(nl.slice().sort()) === JSON.stringify(unl.slice().sort()), { nl, unl });
      // 광고주 한 장
      await p.click('#tblChips .chip[data-f="all"]');
      await p.click('#tbody tr[data-pid="11"] button.link');
      await p.waitForSelector('#s-client.on');
      await p.waitForFunction(() => document.getElementById('c-name').textContent.length > 0);
      const client = (await api(p, '/clients/11')).body;
      ok('대표: 광고주 한 장 주소 /naver/clients/11', new URL(p.url()).pathname === '/naver/clients/11', p.url());
      ok('대표: 광고주 한 장 이름 = 서버', (await p.textContent('#c-name')) === client.name);
      ok('대표: 광고주 한 장 신호 색 = 서버 판정', (await p.getAttribute('#c-sig', 'class')) === 'sig ' + client.verdict.color);
      await shot(p, '2-대표-광고주한장');
      await p.click('[data-ctab="conn"]');
      ok('대표: 연결 칸이 열린다', await p.isVisible('#p-conn.on'));
      await p.waitForSelector('#c-links .kh');
      await p.goBack();
      await p.waitForSelector('#s-watch.on');
      ok('대표: 뒤로 가면 관제로', new URL(p.url()).pathname === '/naver/');
      // 🔔
      const bell = (await api(p, '/bell')).body;
      await p.click('#bell');
      await p.waitForSelector('#drawer.on');
      await p.waitForFunction(() => !document.querySelector('#drawerBody .loading'));
      const bn = await p.$$eval('#drawerBody .bitem', (els) => els.length);
      ok('대표: 🔔 줄 수 = 서버', bn === bell.items.length, { bn, want: bell.items.length });
      await p.click('#drawerX');
      // ⚙️ 설정 — 대표는 고칠 수 있다
      await p.click('#menuSettings');
      await p.waitForSelector('#s-settings.on #th-bizmoney_red_days');
      ok('대표: 설정 기준값 칸이 있다(고칠 수 있음)', await p.isVisible('#th-bizmoney_red_days'));
      await shot(p, '3-대표-설정');
      await p.fill('#th-bizmoney_yellow_days', '4');
      await p.click('#sp-th button.btn.blue');
      await p.waitForFunction(() => document.getElementById('toast').textContent.includes('저장'));
      const st = (await api(p, '/settings')).body;
      ok('대표: 기준값 저장이 서버에 반영', st.thresholds.bizmoney_yellow_days === 4, st.thresholds.bizmoney_yellow_days);
      await p.click('[data-sp="sys"]');
      ok('대표: 시스템 칸(붙잡아 둔 목록)이 보인다', (await p.textContent('#sp-sys')).includes('대표님 확인이 필요한 목록'));
      // 50분 갱신
      await p.goto(base + '/naver/');
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const waitRefresh = p.waitForRequest((r) => r.url().endsWith('/api/naver-auto/session/refresh') && r.method() === 'POST', { timeout: 5000 }).then(() => true, () => false);
      await p.clock.fastForward(50 * 60 * 1000 + 1000);
      ok('대표: 50분 뒤 /session/refresh 를 부른다', await waitRefresh);
      await p.waitForTimeout(300);
      const sess2 = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session') || 'null'));
      ok('대표: 갱신한 토큰을 저장한다(끝 시각이 늘어남)', sess2 && sess2.token && sess2.exp > sess.exp, [sess.exp, sess2 && sess2.exp]);
      // 좁은 화면
      await p.setViewportSize({ width: 390, height: 800 });
      await p.waitForTimeout(100);
      const sw = await p.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
      ok('대표: 390px 화면에서 가로로 밀리지 않는다', sw[0] <= sw[1] + 1, sw);
      await shot(p, '4-대표-좁은화면');
      await p.click('#menuSettings');
      await p.waitForSelector('#s-settings.on #th-bizmoney_red_days');
      const bx = await p.$eval('#th-bizmoney_red_days', (e) => { const r = e.getBoundingClientRect(); return [r.left, r.right]; });
      ok('대표: 390px 에서도 기준값 칸이 옆으로 밀지 않고 보인다', bx[0] >= 0 && bx[1] <= 390, bx);
      await p.click('[data-go="/naver/"]');
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      await hygiene('대표', p, log, url);
      await ctx.close();
    }

    // ── 새로 고침 뒤에도 토큰 끝 시각에서 센다(검토 refresh-timer-reset) ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      await p.clock.install();
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.ceo3);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const s0 = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session')));
      await p.mouse.click(5, 5);
      await p.clock.fastForward(40 * 60 * 1000);
      await p.reload();
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const t1 = await p.evaluate(() => Date.now());
      ok('F5: 새로 고침 뒤에도 가짜 시계가 이어진다(시험 전제)', t1 - s0.exp > -21 * 60 * 1000, [t1, s0.exp]);
      const waitR = p.waitForResponse((r) => r.url().endsWith('/api/naver-auto/session/refresh') && r.status() === 200, { timeout: 8000 }).then(() => true, () => false);
      await p.mouse.click(5, 5);
      await p.clock.runFor(10 * 60 * 1000 + 2000);
      ok('F5: 새로 고침 10분 뒤(토큰 끝 10분 전) 갱신한다', await waitR);
      await p.waitForTimeout(200);
      await p.clock.runFor(11 * 60 * 1000);
      await p.waitForTimeout(200);
      ok('F5: 옛 토큰 끝 시각이 지나도 들어와 있다', await p.isVisible('#s-watch.on'));
      const s1 = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session') || 'null'));
      ok('F5: 토큰 끝 시각이 늘었다', s1 && s1.exp > s0.exp, [s0.exp, s1 && s1.exp]);
      await hygiene('F5', p, log, url);
      await ctx.close();
    }

    // ── 모니터링용 무활동 4시간 전에는 유지하고 4시간 뒤에는 끝낸다 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      await p.clock.install();
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.idle101);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      await p.clock.runFor(30 * 60 * 1000);
      await p.click('#tblChips .chip[data-f="all"]');       // 사람이 손댐 — 쉰 시간이 다시 0 부터
      const waitR = p.waitForResponse((r) => r.url().endsWith('/api/naver-auto/session/refresh'), { timeout: 8000 }).then(() => true, () => false);
      await p.clock.runFor(21 * 60 * 1000);
      ok('쉼: 손댄 뒤에는 토큰 끝 10분 전에 갱신한다', await waitR);
      await p.waitForTimeout(200);
      await p.clock.runFor(35 * 60 * 1000);
      ok('쉼: 손댄 뒤 1시간이 안 되면 들어와 있다', await p.isVisible('#s-watch.on'));
      await p.clock.runFor(180 * 60 * 1000);
      ok('쉼: 무활동 4시간 전에는 모니터링을 유지한다', await p.isVisible('#s-watch.on'));
      await p.clock.runFor(5 * 60 * 1000);
      await p.waitForSelector('#s-blocked.on');
      ok('쉼: 4시간 넘게 손대지 않으면 「오래 쉬어 로그인을 끝냈습니다」', (await p.textContent('#b-t')).includes('오래 쉬어'));
      ok('쉼: 토큰을 지운다', (await p.evaluate(() => sessionStorage.getItem('naverWatch.session'))) === null);
      await hygiene('쉼', p, log, url);
      await ctx.close();
    }

    // ── 갱신이 한 번 실패해도 1분 뒤 다시 한다(검토 refresh-no-retry) ──
    {
      const { ctx, log } = await newCtx(browser);
      let refreshCalls = 0;
      await ctx.route('**/api/naver-auto/session/refresh', async (route) => {
        refreshCalls += 1;
        if (refreshCalls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'engine-timeout' }) });
        return route.continue();
      });
      const p = await page(ctx, log);
      await p.clock.install();
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.retry101);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const s0 = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session')));
      await p.mouse.click(5, 5);
      await p.clock.runFor(50 * 60 * 1000 + 2000);
      await p.waitForTimeout(300);
      ok('갱신 실패: 토큰 끝 10분 전에 한 번 부른다(첫 번은 503)', refreshCalls === 1, refreshCalls);
      const ok200 = p.waitForResponse((r) => r.url().endsWith('/api/naver-auto/session/refresh') && r.status() === 200, { timeout: 8000 }).then(() => true, () => false);
      await p.mouse.click(5, 5);
      await p.clock.runFor(2 * 60 * 1000 + 2000);   // 실패 1분 뒤부터 · 1분마다 살피므로 늦어도 2분 안
      ok('갱신 실패: 1분 넘게 지나 다시 불러 성공한다', await ok200, refreshCalls);
      await p.waitForTimeout(200);
      const s1 = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session') || 'null'));
      ok('갱신 실패: 다시 한 뒤 토큰 끝 시각이 늘었다', s1 && s1.exp > s0.exp, [s0.exp, s1 && s1.exp]);
      log.statuses = log.statuses.filter((x) => !(x[0] === 503 && x[1].startsWith('/api/naver-auto/session/refresh')));   // 일부러 낸 실패
      await hygiene('갱신 실패', p, log, url);
      await ctx.close();
    }

    // ── 경합 · 늦은 답 — 첫 불러오기 실패 · 빠른 범위 바꾸기 · 누른 뒤 다른 화면 · 광고주 바꿈 · 🔔 먼저 누름 · 두 번 누름 ──
    {
      const { ctx, log } = await newCtx(browser);
      const delay = (ms) => new Promise((res) => setTimeout(res, ms));
      let failBoard = true;
      await ctx.route('**/api/naver-auto/board*', async (route) => {
        if (failBoard) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'org-unavailable' }) });
        if (route.request().url().includes('selection=me')) await delay(900);
        return route.continue();
      });
      const p = await page(ctx, log);
      await p.clock.install({ time: new Date('2026-09-29T23:57:00+09:00') });   // 자정 넘김 시험용(맨 끝)
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.ceo4);
      await p.waitForSelector('#watchSync[data-status="error"] button');
      const msg = await p.textContent('#watchSync');
      ok('경합: 첫 불러오기 실패 = 권한·조직 확인 불가 + 「다시 확인」', msg.includes('자료를 표시하지 않았습니다') && msg.includes('현재 권한·조직 자료를 확인할 수 없습니다') && msg.includes('다시 확인'), msg);
      ok('경합: 첫 실패는 검증 게이트를 닫고 업체·이슈·숫자 DOM을 남기지 않는다',
        await p.locator('#s-watch.view-unverified').count() === 1 &&
        await p.locator('#tbody tr[data-pid], #issues .iss, #kpis .kpi').count() === 0 && await p.isHidden('#q'));
      failBoard = false;
      await p.click('#watchSync button');
      await p.waitForSelector('#watchSync[data-status="current"]');
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      ok('경합: 다시 확인 성공 뒤에만 게이트를 열고 숫자 칸이 나온다',
        await p.locator('#s-watch.view-unverified').count() === 0 && (await p.$$eval('#kpis .kpi', (els) => els.length)) === 4);
      await p.click('#tblChips .chip[data-f="all"]');
      await p.fill('#q', '가');
      await p.fill('#q', '');
      failBoard = true;
      await p.click('#watchReload');
      await p.waitForSelector('#watchSync[data-status="error"] button');
      ok('경합: 성공 뒤 조직 확인 실패도 옛 업체·이슈·숫자 DOM을 지우고 검색을 숨긴다',
        await p.locator('#s-watch.view-unverified').count() === 1 &&
        await p.locator('#tbody tr[data-pid], #issues .iss, #kpis .kpi').count() === 0 && await p.isHidden('#q'));
      failBoard = false;
      await p.click('#watchSync button');
      await p.waitForSelector('#watchSync[data-status="current"]');
      ok('경합: 권한 실패 뒤 다시 확인으로 현재 업체가 복구된다',
        await p.locator('#s-watch.view-unverified').count() === 0 && await p.locator('#tbody tr[data-pid]').count() > 0);
      log.statuses = log.statuses.filter((x) => !(x[0] === 503 && x[1].startsWith('/api/naver-auto/board')));   // 일부러 낸 실패
      // 빠른 범위 바꾸기 — 늦게 오는 「내 담당만」 답이 「전체」를 덮지 않는다
      const all = (await api(p, '/board?selection=all&attention=0')).body.today_counts;
      await p.selectOption('#scope', 'me');
      await p.selectOption('#scope', 'all');
      await p.waitForTimeout(1500);
      const kv = await p.$$eval('#kpis .kpi .v', (els) => els.map((e) => e.textContent));
      ok('경합: 범위를 빨리 바꿔도 마지막 고른 범위의 숫자', JSON.stringify(kv) === JSON.stringify([all.need, all.ok, all.unlinked, all.unchecked].map(fmt)) && (await p.inputValue('#scope')) === 'all', kv);
      // 두 번 누름 · 누른 뒤 다른 화면 — 답이 늦게 와도 설정 화면에 머문다
      await ctx.route('**/api/naver-auto/issues/*/ack', async (route) => { await delay(700); return route.continue(); });
      const before = log.requests.length;
      const row = '#issues .iss[data-issue="' + cfg.red + '"]';
      await p.waitForSelector(row + ' button:has-text("확인 중")');
      const clicked = await p.$eval(row + ' .act button', (b) => { const t = b.textContent; b.click(); b.click(); return t; });
      await p.click('#menuSettings');
      await p.waitForTimeout(1300);
      const acks = log.requests.slice(before).filter((r) => /\/issues\/\d+\/ack$/.test(r.url) && r.method === 'POST').length;
      ok('경합: 👀 를 두 번 눌러도 한 번만 보낸다', acks === 1, { acks, clicked });
      ok('경합: 누른 뒤 설정으로 옮기면 늦은 답이 관제로 끌고 오지 않는다', new URL(p.url()).pathname === '/naver/settings' && await p.isVisible('#s-settings.on') && !(await p.isVisible('#s-watch.on')), p.url());
      // 광고주 바꿈 — 앞 광고주의 이름·연결 칸이 남지 않는다
      await p.click('[data-go="/naver/"]');
      await p.waitForSelector('#s-watch.on #tbody tr');
      await p.click('#tblChips .chip[data-f="all"]');
      await p.click('#tbody tr[data-pid="11"] button.link');
      await p.waitForFunction(() => document.getElementById('c-name').textContent.length > 0);
      await p.click('[data-ctab="conn"]');
      await p.goBack();
      await p.waitForSelector('#s-watch.on');
      await ctx.route('**/api/naver-auto/clients/12', async (route) => { await delay(900); return route.continue(); });
      await p.click('#tblChips .chip[data-f="all"]');
      await p.click('#tbody tr[data-pid="12"] button.link');
      await p.waitForSelector('#s-client.on');
      const mid = await p.evaluate(() => [document.getElementById('c-name').textContent, document.getElementById('p-conn').classList.contains('on'),
                                          document.querySelectorAll('#p-conn button').length]);
      ok('경합: 다른 광고주를 여는 동안 앞 광고주 이름·연결 칸·단추가 없다', mid[0] === '' && mid[1] === false && mid[2] === 0, mid);
      await p.waitForFunction(() => document.getElementById('c-name').textContent.length > 0);
      const c12 = (await api(p, '/clients/12')).body;
      ok('경합: 다 불러오면 새 광고주 이름', (await p.textContent('#c-name')) === c12.name);
      // 🔔 — 목록을 받기 전에는 「모두 읽음」을 누를 수 없다
      await ctx.route('**/api/naver-auto/bell', async (route) => { await delay(800); return route.continue(); });
      await p.click('#bell');
      await p.waitForSelector('#drawer.on');
      ok('경합: 🔔 목록을 받기 전 「모두 읽음」은 잠겨 있다', await p.isDisabled('#bellAll'));
      await p.waitForFunction(() => !document.querySelector('#drawerBody .loading'));
      ok('경합: 🔔 목록을 받으면 「모두 읽음」이 풀린다', await p.isEnabled('#bellAll'));
      await p.keyboard.press('Escape');
      // 자정이 지나면 🙈 창을 열기 전에 서버의 오늘로 다시 받는다(끝날이 어제가 되지 않게)
      const yrow = '#issues .iss[data-issue="' + cfg.yellow + '"]';
      const reentered = p.waitForResponse((r) => r.url().includes('/api/naver-auto/board') && r.status() === 200);
      await p.click('[data-go="/naver/"]');
      await reentered;
      await p.waitForSelector('#watchSync[data-status="current"]');   // unchanged면 기존 DOM을 보존할 수 있다.
      await p.waitForSelector(yrow + ' button:has-text("예외")');
      const oldExcept = await p.$(yrow + ' button:has-text("예외")');
      const reloaded = p.waitForResponse((r) => r.url().includes('/api/naver-auto/board') && r.status() === 200, { timeout: 10000 }).then(() => true, () => false);
      await p.click(yrow + ' button:has-text("예외")');
      await p.waitForSelector('#m-except.on');
      await p.clock.fastForward(5 * 60 * 1000);
      ok('경합: 자정을 넘기면 열려 있던 옛 🙈 창을 닫는다', !(await p.isVisible('#m-except.on')));
      ok('경합: 자정 뒤 관제 판을 서버에서 다시 받는다', await reloaded);
      await p.waitForFunction((el) => !el.isConnected, oldExcept);   // 날짜 경계에서는 옛 권한의 DOM을 버린다.
      await p.waitForSelector('#watchSync[data-status="current"]');
      await p.waitForSelector(yrow + ' button:has-text("예외")');
      await p.click(yrow + ' button:has-text("예외")');
      await p.waitForSelector('#m-except.on');
      ok('경합: 새로 불러온 뒤에는 🙈 창이 열린다', await p.isVisible('#m-except.on'));
      await p.keyboard.press('Escape');
      await hygiene('경합', p, log, url);
      await ctx.close();
    }

    // ── 담당(101) — 알림 링크 주소로 들어옴 · 설정·범위 고르기 없음 · 👀 확인 중 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/issues';
      await enter(p, url, cfg.sso.s101);
      await p.waitForSelector('#s-watch.on #issues .iss');
      ok('담당: /naver/issues 로 들어와도 관제 화면', new URL(p.url()).pathname === '/naver/issues');
      ok('담당: 설정 메뉴가 없다', await p.isHidden('#menuSettings'));
      ok('담당: 보는 범위 고르기가 없다', await p.isHidden('#scope'));
      const row = '#issues .iss[data-issue="' + cfg.yellow + '"]';
      await p.waitForSelector(row);
      await p.click(row + ' button:has-text("확인 중")');
      await p.waitForFunction(() => document.getElementById('toast').textContent.includes('확인 중'));
      await p.waitForFunction((sel) => !document.querySelector(sel + ' button') || !Array.from(document.querySelectorAll(sel + ' button')).some((b) => b.textContent.includes('확인 중')), row);
      const b = (await api(p, '/board?attention=0')).body;
      const got = b.issue_rows.filter((r) => r.issue_id === cfg.yellow)[0];
      ok('담당: 👀 누르면 서버 상태가 확인 중', got && got.state === 'ack', got && got.state);
      const pids = (await api(p, '/board?attention=0')).body.rows.map((r) => r.possibility_id);
      await p.click('#tblChips .chip[data-f="all"]');
      const drawn = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => Number(e.getAttribute('data-pid'))));
      ok('담당: 표는 내 담당만(서버와 같음)', JSON.stringify(drawn.sort()) === JSON.stringify(pids.sort()), drawn);
      await hygiene('담당', p, log, url);
      await ctx.close();
    }

    // ── 2026-10-02 명세: 관리팀장(1)도 본인 담당만 — 이 fixture에는 직접 담당이 없다 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.lead);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const me = (await api(p, '/me')).body;
      ok('관리팀장: TEAM이 아니라 MINE', me.scope === 'MINE', me.scope);
      ok('관리팀장: 팀 목록 없음 · 직원 명단은 본인만', me.teams.length === 0 &&
        JSON.stringify(me.people.map((person) => person.idx)) === '[1]', { teams: me.teams, people: me.people });
      ok('관리팀장: 설정과 범위 고르기가 없다', await p.isHidden('#menuSettings') && await p.isHidden('#scope'));
      const board = (await api(p, '/board?attention=0')).body;
      ok('관리팀장: 직접 담당이 없으면 팀원 광고주·이슈도 0', board.rows.length === 0 &&
        board.issue_rows.length === 0 && board.done_rows.length === 0, board.rows);
      ok('관리팀장: 화면에 팀원 광고주·승인 버튼이 없다',
        await p.locator('#tbody tr[data-pid], #issues .iss .act button').count() === 0);
      const denied = ['/clients/11', '/clients/12', '/board?selection=person:100', '/board?selection=team:11'];
      for (const path of denied) {
        const result = await api(p, path);
        ok('관리팀장: 직접 요청도 범위 밖 404 ' + path, result.status === 404, result);
      }
      const exceptPath = '/issues/' + cfg.red + '/except';
      const refused = await api(p, exceptPath, 'POST', { until: board.band.today, note: '타 담당 직접 요청' });
      ok('관리팀장: 타 담당 긴급 예외 직접 승인도 404', refused.status === 404, refused);
      await shot(p, '5-관리팀장-본인담당');
      // 의도한 권한 거절만 제외한다. 화면 파일 404와 뜻밖의 응답 검사는 그대로 유지한다.
      const expected404 = new Set(denied.concat(exceptPath).map((path) => '/api/naver-auto' + path));
      log.statuses = log.statuses.filter((entry) => !(entry[0] === 404 && expected404.has(entry[1])));
      await hygiene('관리팀장', p, log, url);
      await ctx.close();
    }

    // ── 2026-10-02 명세: 타 담당 🔴 예외 승인은 대표만 — 기간·사유 저장 회귀는 유지한다 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.exceptionCeo);
      const row = '#issues .iss[data-issue="' + cfg.red + '"]';
      await p.waitForSelector(row);
      await p.click(row + ' button:has-text("예외")');
      await p.waitForSelector('#m-except.on');
      await shot(p, '5b-대표-예외창');
      const opts = await p.$$eval('#mx-days option', (els) => els.map((e) => e.value));
      ok('대표: 🔴 예외 기간은 7일 안에서만 고른다', opts.length >= 2 && opts.length <= 3, opts);
      await p.fill('#mx-why', '광고주가 자동 충전 켬');
      await p.selectOption('#mx-days', opts[1]);
      await p.click('#mx-ok');
      await p.waitForFunction(() => document.getElementById('toast').textContent.includes('예외'));
      const b = (await api(p, '/board?attention=0')).body;
      const got = b.done_rows.filter((r) => r.issue_id === cfg.red)[0];
      ok('대표: 예외가 서버에 · 고른 끝날 · 사유', got && got.state === 'exception' && got.exception_until === opts[1] && got.hand && got.hand.note === '광고주가 자동 충전 켬', got);
      await hygiene('대표 예외', p, log, url);
      await ctx.close();
    }

    // ── 담당(100) — 설정 주소를 직접 열어도 · 세션이 끝나면 다시 들어오라고 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/settings';
      await enter(p, url, cfg.sso.s100);
      await p.waitForSelector('#s-settings.on');
      ok('담당: 설정 주소를 직접 열면 「담당자는 설정을 보지 않습니다」', (await p.textContent('#set-ps')).includes('담당자는 설정을 보지 않습니다'));
      await p.click('[data-go="/naver/"]');
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      ok('담당: 시간이 지나기 전에는 들어와 있다', await p.isVisible('#s-watch.on'));
      await control('advance?minutes=61');
      await p.click('#tblChips .chip[data-f="all"]');
      await p.click('#tbody tr[data-pid="11"] button.link');
      await p.waitForSelector('#s-blocked.on');
      ok('담당: 토큰이 끝나면 「다시 들어와 주세요」', (await p.textContent('#b-t')).includes('다시 들어와 주세요'));
      const left = await p.evaluate(() => sessionStorage.getItem('naverWatch.session'));
      ok('담당: 끝난 토큰은 지운다', left === null, left);
      await hygiene('담당100', p, log, url);
      await ctx.close();
    }


    // ── 서버 값을 그대로 그리나 — 관제 판 응답을 일부러 다른 숫자·앞뒤가 안 맞는 줄로 바꿔 넣는다 ──
    {
      const { ctx, log } = await newCtx(browser, { foldClosed: true });
      const fake = {
        band: { today: '2026-09-29', deadline_passed: true, runs: [], pairing_at: null, pairing_today: true, org_freshness: 'fresh', org_generated_at: null, stage_as_of: null },
        counts: { red: 5, yellow: 3, green: 7, white: 2, needs_attention: 9, total: 17 },
        today_counts: { need: 11, need_red: 4, ok: 3, unlinked: 2, unchecked: 1 },
        white_breakdown: { unlinked: { id_missing: 2 }, unchecked: { weekly_watch: 1 } }, account_confirm: 0,
        links: { listed: 4, missing: 6, broken: 8, not_linked: 10, none: 1, pending: 0, unlinked_numbers: 12 },
        issues: [], done_rows: [], escalated_to_me: [], attention_only: false, selection: 'all',
        issue_rows: [901, 902].map((n) => ({ issue_id: n, possibility_id: 901, name: '예시가', owner: { name: '담당가' }, relation: 'all',
          code: 'bizmoney_empty', rule: 'bizmoney', severity: 'red', state: 'new', stored_state: 'new', first_seen_on: '2026-09-29',
          last_seen_on: '2026-09-29', reappear_count: 0, exception_until: null, facts: {}, target_tail: String(1000 + n), updated_at: null,
          hand: null, can: { ack: true, resolve: true, except: false, except_until_max: null, except_blocked: 'actor-too-low' } })),
        rows: [
          { possibility_id: 901, name: '예시가', stage: '진행중', relation: 'all', owner: { name: '담당가', team_name: '팀가' },
            verdict: { color: 'green', needs_attention: false, reasons: [], white_reason: null }, open_red: 3, open_yellow: 0,
            account_unconfirmed: false, link: 'listed', yday_spend: 1200, bizmoney: 50000, look_today: false, today_group: 'ok', white_detail: null },
          { possibility_id: 902, name: '예시나', stage: '환불중', relation: 'all', owner: { name: '담당가', team_name: '팀가' },
            verdict: { color: 'white', needs_attention: true, reasons: ['key_rejected'], white_reason: 'key_rejected' }, open_red: 0, open_yellow: 0,
            account_unconfirmed: false, link: 'broken', yday_spend: null, bizmoney: null, look_today: true, today_group: 'need', white_detail: 'key_rejected' },
          { possibility_id: 903, name: '예시다', stage: '계약만료', relation: 'all', owner: { name: null, team_name: null },
            verdict: { color: 'red', needs_attention: true, reasons: ['open-red'], white_reason: null }, open_red: 0, open_yellow: 0,
            account_unconfirmed: true, link: 'missing', yday_spend: 0, bizmoney: 0, look_today: true, today_group: 'need', white_detail: null },
          { possibility_id: 904, name: '예시라', stage: '진행중', relation: 'all', owner: { name: '담당가', team_name: '팀가' },
            verdict: { color: 'green', needs_attention: false, reasons: [], white_reason: null }, open_red: 0, open_yellow: 0,
            account_unconfirmed: false, link: 'listed', unlinked: true, yday_spend: 10, bizmoney: 20, look_today: false, today_group: 'unlinked', white_detail: null }
        ]
      };
      await ctx.route('**/api/naver-auto/board*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fake) }));
      const fakeClient = {
        possibility_id: 901, name: '예시가', stage: '진행중', managed: true, today: '2026-09-29', latest_end_date: null, relation: 'all',
        owner: { name: '담당가', team_name: '팀가' }, verdict: { color: 'white', needs_attention: true, reasons: [], white_reason: 'partial' },
        accounts: [{ tail: '1234', account_name: null, link: 'confirmed', state: 'confirmed', history: [{
          day: new Date(Date.now() + 9 * 3600000).toISOString().slice(0,10), status: 'partial', yday_spend: 999999,
          rules_not_run: [['D1','checkpoint-too-large'],['D2','checkpoint-too-large']] }] },
                   { tail: '5678', account_name: null, link: 'confirmed', state: 'confirmed', history: [{
          day: new Date(Date.now() + 9 * 3600000).toISOString().slice(0,10), status:'partial',
          rules_not_run:[['D1','checkpoint-invalid']] }] }],
        issues: [], link: 'listed', unlinked: false, account_unconfirmed: false,
        yday_spend: null, bizmoney: 5000, yday_imp: null, yday_clk: 3,
        days: [{ day: '2026-09-28', yday_spend: 100, complete: false }, { day: '2026-09-29', yday_spend: 200, complete: true }],
        // 기존 API의 lead 등급은 이제 대표에게만 부여된다(팀장 직책 권한을 뜻하지 않는다).
        report: 'preparing', actions: { handle_issue: true, confirm_link: true, exception_actor: 'lead', exception_max_days: { red: 7, yellow: 30 }, raising_allowed: true }
      };
      await ctx.route('**/api/naver-auto/clients/901', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fakeClient) }));
      await ctx.route('**/api/naver-auto/links/pending', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ pairing_at: null, rows: [], decisions: [] }) }));
      const p = await page(ctx, log);
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.ceo2);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const kv = await p.$$eval('#kpis .kpi .v', (els) => els.map((e) => e.textContent));
      ok('가짜 값: 숫자 4칸이 서버 값 그대로(오늘 볼 곳 · 문제없음 · 연결 안 됨 · 점검 못 함 순)', JSON.stringify(kv) === JSON.stringify(['11', '3', '2', '1']), kv);
      ok('가짜 값: 전체 광고주 표는 접혀서 시작한다', (await p.$eval('#allFold', (d) => d.open)) === false);
      await p.click('#kpis .kpi.cut');
      ok('가짜 값: 「🔌 연결 안 됨」 칸을 누르면 접힌 표가 열리고 서버가 연결 안 됨이라 한 줄만', (await p.$eval('#allFold', (d) => d.open)) === true &&
        JSON.stringify(await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => e.getAttribute('data-pid')))) === JSON.stringify(['904']));
      const advOrder = await p.$$eval('#issues .adv', (els) => els.map((e) => e.getAttribute('data-pid')));
      ok('가짜 값: 오늘 볼 광고주 = 서버 「오늘 볼 곳」 + 열린 이슈 줄 · 긴급(서버 색) 먼저', JSON.stringify(advOrder) === JSON.stringify(['903', '901', '902']), advOrder);
      const note902 = await p.textContent('#issues .adv[data-pid="902"]');
      ok('가짜 값: 이슈 없이 오늘 볼 곳은 서버 까닭과 할 일 한 줄', note902.includes('읽기 거절 · 이관 남음') && note902.includes('할 일 · 광고주에게 우리 회사 권한(운영관리)이 바뀌었는지 확인 요청'), note902);
      await p.click('#tblChips .chip[data-f="all"]');
      const iw = await p.textContent('#iwan');
      ok('가짜 값: 이관 띠가 서버 값 그대로', ['이관됨 4', '🔌 이관 빠짐 8', '오늘 목록에 없음 6', '이관 안 된 번호 12'].every((t) => iw.includes(t)), iw);
      const head = await p.textContent('#issues .adv[data-pid="901"] .adv-head');
      ok('가짜 값: 광고주 머리에 그 광고주의 열린 이슈 수(한 광고주의 계정 둘 = 한 덩어리 · 이슈 2건)', head.includes('예시가') && head.includes('이슈 2건') &&
        (await p.$$eval('#issues .adv[data-pid="901"] .iss', (els) => els.length)) === 2, head);
      const note = await p.$$eval('#issues .iss .blocked-note', (els) => els.map((e) => e.textContent));
      const dis = await p.$$eval('#issues .iss button[disabled]', (els) => els.length);
      // 2026-10-02 명세: 긴급 예외를 팀장 권한으로 안내하지 않는다.
      ok('가짜 값: 막힌 🙈 는 흐린 단추가 아니라 대표 승인 안내', note.length === 2 &&
        note.every((t) => t.includes('대표') && !t.includes('팀장')) && dis === 0, { note, dis });
      await p.click('#tblChips .chip[data-f="all"]');
      const drawn = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => [e.getAttribute('data-pid'), e.querySelector('.sig').className, e.querySelector('.hint').textContent, e.children[2].textContent, e.children[3].textContent]));
      ok('가짜 값: 열린 🔴 가 있어도 서버가 🟢 라면 🟢(화면이 판정하지 않는다)', drawn.some((d) => d[0] === '901' && d[1] === 'sig green' && d[2] === '정상' && d[3] === '—'), drawn);
      ok('가짜 값: ⚪ 사유 글자 · 확인 필요 · 이관 빠짐', drawn.some((d) => d[0] === '902' && d[1] === 'sig white' && d[2] === '읽기 거절 · 이관 남음' && d[3] === '확인 필요' && d[4] === '🔌 이관 빠짐'), drawn);
      ok('가짜 값: 열린 이슈 0 이어도 서버가 🔴 라면 🔴', drawn.some((d) => d[0] === '903' && d[1] === 'sig red' && d[4] === '오늘 목록에 없음'), drawn);
      ok('가짜 값: 이관 칸에 「+ 이관 안 된 번호」(이관됨과 함께)', drawn.some((d) => d[0] === '904' && d[4].includes('이관됨') && d[4].includes('+ 이관 안 된 번호')), drawn);
      await p.click('#tblChips .chip[data-f="white"]');
      const wv = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => e.getAttribute('data-pid')));
      ok('가짜 값: 「점검 불가」 칸은 서버 색이 ⚪ 인 줄만', JSON.stringify(wv) === JSON.stringify(['902']), wv);
      await p.click('#iwan .ichip:has-text("이관 안 된 번호")');
      const uv = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => e.getAttribute('data-pid')));
      ok('가짜 값: 「이관 안 된 번호」는 서버 표시(unlinked)가 있는 줄만', JSON.stringify(uv) === JSON.stringify(['904']), uv);
      // 광고주 한 장 타일 · 막대 = 서버 값 그대로(계정별 기록을 화면이 다시 더하지 않는다 · 모르면 — · 일부만 읽은 날은 흐리게)
      await p.click('#tblChips .chip[data-f="all"]');
      await p.click('#tbody tr[data-pid="901"] button.link');
      await p.waitForFunction(() => document.getElementById('c-name').textContent === '예시가');
      const tiles = await p.$$eval('#p-now .tile .v', (els) => els.map((e) => e.textContent));
      ok('가짜 값: 광고주 한 장 타일 = 서버 값(모르면 — · 0원으로 채우지 않음)', JSON.stringify(tiles) === JSON.stringify(['—', '—', '3', '5,000원']), tiles);
      const checkpointText = await p.textContent('#p-now');
      ok('가짜 값: 큰 자료·이어읽기 기록 문제를 계정별 쉬운 말로 표시',
        /1234.*광고 자료가 커서 상세 점검을 보류/.test(checkpointText) &&
        /5678.*읽던 위치의 기록을 확인할 수 없어 새로 점검/.test(checkpointText) &&
        (checkpointText.match(/광고 자료가 커서 상세 점검을 보류/g)||[]).length === 1, checkpointText);
      const bars = await p.$$eval('#p-now .sbars i', (els) => els.map((e) => e.className));
      ok('가짜 값: 14일 막대 = 서버 날짜별 합(일부만 읽은 날은 흐리게)', JSON.stringify(bars) === JSON.stringify(['part', '']), bars);
      await ctx.close();
    }

    // ── 실제 수신부+앱: 새 창 연결 없는 진입은 원인별 안내만 표시하고 인증 요청은 보내지 않는다 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const requestId = 'R'.repeat(43);
      const url = base + '/naver/?sso_start=' + requestId;
      await p.goto(url);   // enter()의 수신부 대체를 쓰지 않는다.
      await p.waitForSelector('#s-blocked.on');
      const title = await p.textContent('#b-t');
      const message = await p.textContent('#b-p');
      ok('진입 진단: 새 창 연결 없음은 서버 장애가 아닌 NV-E04', title.includes('전산 창과의 연결이 없습니다') && message.includes('진단 코드: NV-E04'));
      ok('진입 진단: 공식 전산 메뉴와 안전한 캡처 안내', message.includes('광고 스튜디오 › 네이버 관제') && message.includes('주소창을 제외'));
      ok('진입 진단: 요청 번호·원문 주소를 화면에 표시하지 않는다', !message.includes(requestId) && !/https?:\/\//.test(message));
      ok('진입 진단: 인증 요청과 저장 세션 없음', !log.requests.some(r => r.url.includes('/api/naver-auto/')) &&
        (await p.evaluate(() => sessionStorage.getItem('naverWatch.session'))) === null);
      await shot(p, '7-직원진입진단');
      await hygiene('진입 진단', p, log, url);
      await ctx.close();
    }

    // ── 들어올 길 없음 · ① 이 거절한 sso ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      await p.goto(base + '/naver/');
      await p.waitForSelector('#s-blocked.on');
      ok('sso 없이 열면 「전산에서 들어와 주세요」', (await p.textContent('#b-t')).includes('전산에서 들어와 주세요'));
      await shot(p, '6-들어올길없음');
      const url = base + '/naver/';
      await enter(p, url, cfg.sso.bad);
      await p.waitForSelector('#s-blocked.on');
      await p.waitForFunction(() => document.getElementById('b-t').textContent.includes('확인하지 못했습니다'));
      ok('① 이 거절한 sso 도 주소창에서 지운다', !/sso/i.test(p.url()), p.url());
      ok('① 이 거절한 sso 는 저장하지 않는다', (await p.evaluate(() => sessionStorage.getItem('naverWatch.session'))) === null);
      await hygiene('거절', p, log, url);
      await ctx.close();
    }
  } catch (e) {
    ok('시나리오가 끝까지 돌았다', false, String(e && e.stack || e));
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(results) + '\n');
})();
