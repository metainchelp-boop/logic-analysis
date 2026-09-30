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
  const ctx = await browser.newContext(Object.assign({ locale: 'ko-KR', timezoneId: 'Asia/Seoul' }, opts || {}));
  const log = { requests: [], external: [], csp: [], errors: [], statuses: [] };
  await ctx.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith(base + '/')) return route.continue();
    log.external.push(u);
    return route.abort();
  });
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
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.ceo);
      await p.goto(url);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      await p.waitForSelector('#issues .iss');
      await shot(p, '1-대표-관제');
      const sess = await p.evaluate(() => JSON.parse(sessionStorage.getItem('naverWatch.session') || 'null'));
      ok('대표: 자체 토큰이 sessionStorage 「naverWatch.session」에', sess && typeof sess.token === 'string' && sess.token.startsWith('v1.'));
      ok('대표: sso 원문은 저장소 어디에도 없다', !JSON.stringify(sess).includes(cfg.sso.ceo));
      const board = (await api(p, '/board?selection=all&attention=0')).body;
      const kv = await p.$$eval('#kpis .kpi .v', (els) => els.map((e) => e.textContent));
      const c = board.counts;
      ok('대표: 숫자 5칸 = 서버 숫자', JSON.stringify(kv) === JSON.stringify([c.needs_attention, c.red, c.yellow, c.green, c.white].map(fmt)), kv);
      await p.click('#tblChips .chip[data-f="all"]');
      const drawn = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => [Number(e.getAttribute('data-pid')), e.getAttribute('data-color'), e.querySelector('.sig').className]));
      const want = board.rows.map((r) => [r.possibility_id, r.verdict.color, 'sig ' + r.verdict.color]).sort((a, b) => a[0] - b[0]);
      ok('대표: 표의 색 = 서버 판정(한 줄씩)', JSON.stringify(drawn.slice().sort((a, b) => a[0] - b[0])) === JSON.stringify(want), { drawn, want });
      const iss = await p.$$eval('#issues .iss', (els) => els.map((e) => Number(e.getAttribute('data-issue'))));
      ok('대표: 오늘의 이슈 줄 = 서버 이슈 줄', JSON.stringify(iss) === JSON.stringify(board.issue_rows.map((r) => r.issue_id)), { iss });
      const need = await p.$$eval('#kpis .kpi', (els) => els.length);
      ok('대표: 숫자 칸 5개', need === 5, need);
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
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.ceo3);
      await p.goto(url);
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

    // ── 1시간 넘게 손대지 않으면 이 창의 로그인을 끝낸다(검토 idle-refresh-forever) ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      await p.clock.install();
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.idle101);
      await p.goto(url);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      await p.clock.runFor(30 * 60 * 1000);
      await p.click('#tblChips .chip[data-f="all"]');       // 사람이 손댐 — 쉰 시간이 다시 0 부터
      const waitR = p.waitForResponse((r) => r.url().endsWith('/api/naver-auto/session/refresh'), { timeout: 8000 }).then(() => true, () => false);
      await p.clock.runFor(21 * 60 * 1000);
      ok('쉼: 손댄 뒤에는 토큰 끝 10분 전에 갱신한다', await waitR);
      await p.waitForTimeout(200);
      await p.clock.runFor(35 * 60 * 1000);
      ok('쉼: 손댄 뒤 1시간이 안 되면 들어와 있다', await p.isVisible('#s-watch.on'));
      await p.clock.runFor(30 * 60 * 1000);
      await p.waitForSelector('#s-blocked.on');
      ok('쉼: 1시간 넘게 손대지 않으면 「오래 쉬어 로그인을 끝냈습니다」', (await p.textContent('#b-t')).includes('오래 쉬어'));
      ok('쉼: 토큰을 지운다', (await p.evaluate(() => sessionStorage.getItem('naverWatch.session'))) === null);
      await hygiene('쉼', p, log, url);
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
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.ceo4);
      await p.goto(url);
      await p.waitForSelector('#issues .empty button');
      const msg = await p.textContent('#issues');
      ok('경합: 첫 불러오기 실패 = 까닭 + 「다시 불러오기」(불러오는 중에 멈추지 않음)', msg.includes('불러오지 못했습니다') && msg.includes('조직 자료를 아직 받지 못했습니다') && !msg.includes('불러오는 중'), msg);
      await p.click('#tblChips .chip[data-f="all"]');
      await p.fill('#q', '가');
      await p.fill('#q', '');
      failBoard = false;
      await p.click('#issues .empty button');
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      ok('경합: 다시 불러오면 숫자 칸이 나온다', (await p.$$eval('#kpis .kpi', (els) => els.length)) === 5);
      log.statuses = log.statuses.filter((x) => !(x[0] === 503 && x[1].startsWith('/api/naver-auto/board')));   // 일부러 낸 실패
      // 빠른 범위 바꾸기 — 늦게 오는 「내 담당만」 답이 「전체」를 덮지 않는다
      const all = (await api(p, '/board?selection=all&attention=0')).body.counts;
      await p.selectOption('#scope', 'me');
      await p.selectOption('#scope', 'all');
      await p.waitForTimeout(1500);
      const kv = await p.$$eval('#kpis .kpi .v', (els) => els.map((e) => e.textContent));
      ok('경합: 범위를 빨리 바꿔도 마지막 고른 범위의 숫자', JSON.stringify(kv) === JSON.stringify([all.needs_attention, all.red, all.yellow, all.green, all.white].map(fmt)) && (await p.inputValue('#scope')) === 'all', kv);
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
      await hygiene('경합', p, log, url);
      await ctx.close();
    }

    // ── 담당(101) — 알림 링크 주소로 들어옴 · 설정·범위 고르기 없음 · 👀 확인 중 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/issues?sso=' + encodeURIComponent(cfg.sso.s101);
      await p.goto(url);
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

    // ── 팀장(1) — 🔴 예외 창 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.lead);
      await p.goto(url);
      const row = '#issues .iss[data-issue="' + cfg.red + '"]';
      await p.waitForSelector(row);
      await p.click(row + ' button:has-text("예외")');
      await p.waitForSelector('#m-except.on');
      await shot(p, '5-팀장-예외창');
      const opts = await p.$$eval('#mx-days option', (els) => els.map((e) => e.value));
      ok('팀장: 🔴 예외 기간은 7일 안에서만 고른다', opts.length >= 2 && opts.length <= 3, opts);
      await p.fill('#mx-why', '광고주가 자동 충전 켬');
      await p.selectOption('#mx-days', opts[1]);
      await p.click('#mx-ok');
      await p.waitForFunction(() => document.getElementById('toast').textContent.includes('예외'));
      const b = (await api(p, '/board?attention=0')).body;
      const got = b.done_rows.filter((r) => r.issue_id === cfg.red)[0];
      ok('팀장: 예외가 서버에 · 고른 끝날 · 사유', got && got.state === 'exception' && got.exception_until === opts[1] && got.hand && got.hand.note === '광고주가 자동 충전 켬', got);
      await hygiene('팀장', p, log, url);
      await ctx.close();
    }

    // ── 담당(100) — 설정 주소를 직접 열어도 · 세션이 끝나면 다시 들어오라고 ──
    {
      const { ctx, log } = await newCtx(browser);
      const p = await page(ctx, log);
      const url = base + '/naver/settings?sso=' + encodeURIComponent(cfg.sso.s100);
      await p.goto(url);
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
      const { ctx, log } = await newCtx(browser);
      const fake = {
        band: { today: '2026-09-29', deadline_passed: true, runs: [], pairing_at: null, pairing_today: true, org_freshness: 'fresh', org_generated_at: null, stage_as_of: null },
        counts: { red: 5, yellow: 3, green: 7, white: 2, needs_attention: 9, total: 17 },
        links: { listed: 4, missing: 6, broken: 8, not_linked: 10, none: 1, pending: 0, unlinked_numbers: 12 },
        issues: [], done_rows: [], escalated_to_me: [], attention_only: false, selection: 'all',
        issue_rows: [901, 902].map((n) => ({ issue_id: n, possibility_id: 901, name: '예시가', owner: { name: '담당가' }, relation: 'all',
          code: 'bizmoney_empty', rule: 'bizmoney', severity: 'red', state: 'new', stored_state: 'new', first_seen_on: '2026-09-29',
          last_seen_on: '2026-09-29', reappear_count: 0, exception_until: null, facts: {}, target_tail: String(1000 + n), updated_at: null,
          hand: null, can: { ack: true, resolve: true, except: false, except_until_max: null, except_blocked: 'actor-too-low' } })),
        rows: [
          { possibility_id: 901, name: '예시가', stage: '진행중', relation: 'all', owner: { name: '담당가', team_name: '팀가' },
            verdict: { color: 'green', needs_attention: false, reasons: [], white_reason: null }, open_red: 3, open_yellow: 0,
            account_unconfirmed: false, link: 'listed', yday_spend: 1200, bizmoney: 50000 },
          { possibility_id: 902, name: '예시나', stage: '환불중', relation: 'all', owner: { name: '담당가', team_name: '팀가' },
            verdict: { color: 'white', needs_attention: true, reasons: ['key_rejected'], white_reason: 'key_rejected' }, open_red: 0, open_yellow: 0,
            account_unconfirmed: false, link: 'broken', yday_spend: null, bizmoney: null },
          { possibility_id: 903, name: '예시다', stage: '계약만료', relation: 'all', owner: { name: null, team_name: null },
            verdict: { color: 'red', needs_attention: true, reasons: ['open-red'], white_reason: null }, open_red: 0, open_yellow: 0,
            account_unconfirmed: true, link: 'missing', yday_spend: 0, bizmoney: 0 },
          { possibility_id: 904, name: '예시라', stage: '진행중', relation: 'all', owner: { name: '담당가', team_name: '팀가' },
            verdict: { color: 'green', needs_attention: false, reasons: [], white_reason: null }, open_red: 0, open_yellow: 0,
            account_unconfirmed: false, link: 'listed', unlinked: true, yday_spend: 10, bizmoney: 20 }
        ]
      };
      await ctx.route('**/api/naver-auto/board*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fake) }));
      const p = await page(ctx, log);
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.ceo2);
      await p.goto(url);
      await p.waitForSelector('#s-watch.on #kpis .kpi');
      const kv = await p.$$eval('#kpis .kpi .v', (els) => els.map((e) => e.textContent));
      ok('가짜 값: 숫자 5칸이 서버 값 그대로(확인 필요 · 긴급 · 주의 · 정상 · 점검 불가 순)', JSON.stringify(kv) === JSON.stringify(['9', '5', '3', '7', '2']), kv);
      const iw = await p.textContent('#iwan');
      ok('가짜 값: 이관 띠가 서버 값 그대로', ['이관됨 4', '🔌 이관 빠짐 8', '오늘 목록에 없음 6', '이관 안 된 번호 12'].every((t) => iw.includes(t)), iw);
      const head = await p.textContent('#issues .cause');
      ok('가짜 값: 묶음 머리 「곳」은 광고주 수(한 광고주의 계정 둘 = 1곳 · 계정 2개)', head.includes('1곳 · 계정 2개'), head);
      const note = await p.$$eval('#issues .iss .blocked-note', (els) => els.map((e) => e.textContent));
      const dis = await p.$$eval('#issues .iss button[disabled]', (els) => els.length);
      ok('가짜 값: 막힌 🙈 는 흐린 단추가 아니라 까닭 글자', note.length === 2 && note.every((t) => t.includes('팀장 이상')) && dis === 0, { note, dis });
      await p.click('#tblChips .chip[data-f="all"]');
      const drawn = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => [e.getAttribute('data-pid'), e.querySelector('.sig').className, e.querySelector('.hint').textContent, e.children[2].textContent, e.children[3].textContent]));
      ok('가짜 값: 열린 🔴 가 있어도 서버가 🟢 라면 🟢(화면이 판정하지 않는다)', drawn.some((d) => d[0] === '901' && d[1] === 'sig green' && d[2] === '정상' && d[3] === '—'), drawn);
      ok('가짜 값: ⚪ 사유 글자 · 확인 필요 · 이관 빠짐', drawn.some((d) => d[0] === '902' && d[1] === 'sig white' && d[2] === '읽기 거절 · 이관 남음' && d[3] === '확인 필요' && d[4] === '🔌 이관 빠짐'), drawn);
      ok('가짜 값: 열린 이슈 0 이어도 서버가 🔴 라면 🔴', drawn.some((d) => d[0] === '903' && d[1] === 'sig red' && d[4] === '오늘 목록에 없음'), drawn);
      ok('가짜 값: 이관 칸에 「+ 이관 안 된 번호」(이관됨과 함께)', drawn.some((d) => d[0] === '904' && d[4].includes('이관됨') && d[4].includes('+ 이관 안 된 번호')), drawn);
      await p.click('#kpis .kpi.white');
      const wv = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => e.getAttribute('data-pid')));
      ok('가짜 값: 「점검 불가」 칸은 서버 색이 ⚪ 인 줄만', JSON.stringify(wv) === JSON.stringify(['902']), wv);
      await p.click('#iwan .ichip:has-text("이관 안 된 번호")');
      const uv = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => e.getAttribute('data-pid')));
      ok('가짜 값: 「이관 안 된 번호」는 서버 표시(unlinked)가 있는 줄만', JSON.stringify(uv) === JSON.stringify(['904']), uv);
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
      const url = base + '/naver/?sso=' + encodeURIComponent(cfg.sso.bad);
      await p.goto(url);
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
