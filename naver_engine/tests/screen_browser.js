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
      ok('대표: 이관 띠에 서버 이관 수', iw.includes('이관됨 ' + fmt(board.links.listed)) && iw.includes('이관 안 됨 ' + fmt(board.links.not_linked)), iw);
      await p.click('#iwan .ichip:has-text("이관 안 됨")');
      const nl = await p.$$eval('#tbody tr[data-pid]', (els) => els.map((e) => Number(e.getAttribute('data-pid'))));
      ok('대표: 「이관 안 됨」을 누르면 그 광고주만', JSON.stringify(nl) === JSON.stringify(board.rows.filter((r) => r.link === 'not_linked').map((r) => r.possibility_id)), nl);
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
      await hygiene('대표', p, log, url);
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
