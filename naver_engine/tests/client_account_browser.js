'use strict';
const {chromium} = require('playwright');
const cfg = JSON.parse(process.argv[2]);
const results = [];
function check(name, pass) { results.push({name, pass: !!pass}); }
(async () => {
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({locale:'ko-KR', timezoneId:'Asia/Seoul', viewport:{width:390,height:844}});
    let external = 0;
    await context.route('**/*', route => route.request().url().startsWith(cfg.base + '/') ? route.continue() : (external++, route.abort()));
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({contentType:'application/javascript', body:
      'window.__metaincSso={started:true,legacyPresent:false,consume:function(){return Promise.resolve(' +
      JSON.stringify({code:cfg.sso,codeVerifier:'V'.repeat(42)+'A'}) + ');}};'}));
    const company = () => page.locator('#c-account-scope [data-account-key="company"]');
    const a = () => page.locator('#c-account-scope [data-account-key="' + cfg.a + '"]');
    const e = () => page.locator('#c-account-scope [data-account-key="' + cfg.e + '"]');
    async function spend(value) { await page.waitForFunction(expected => document.querySelector('#p-now .tile .v')?.textContent === expected, value + '원'); }
    async function routeClient(id) { await page.evaluate(id => {history.pushState({}, '', '/naver/clients/' + id);window.dispatchEvent(new PopStateEvent('popstate'));}, id); }
    await page.goto(cfg.base + '/naver/clients/11'); await spend(100);
    check('default company sum / three safe choices', await page.locator('#c-account-scope button').count() === 3);
    check('selected company label', await company().getAttribute('aria-pressed') === 'true');
    await e().click(); await spend(60);
    check('individual account value', await e().getAttribute('aria-pressed') === 'true');
    check('individual verdict supplied by server', await page.locator('#c-sig').getAttribute('class') === 'sig yellow');
    await page.locator('#t-conn').click();
    check('connected account catalog still contains both', await page.locator('#p-conn .masked').count() === 2);
    await page.locator('#t-now').click(); await company().click(); await spend(100);
    const pattern = '**/api/naver-auto/clients/11?account_key=' + cfg.a;
    let release, received = false;
    const held = new Promise(resolve => {release = resolve;});
    await page.route(pattern, async route => {const response = await route.fetch();received = true;await held;await route.fulfill({response});});
    await a().click(); while (!received) await new Promise(resolve => setTimeout(resolve, 10));
    check('switch clears previous financial tiles', await page.locator('#p-now .tile').count() === 0);
    check('switch clears previous issue actions', await page.locator('#p-hist').textContent() === '' && await page.locator('#p-conn').textContent() === '');
    check('loading is announced', await page.locator('#p-now [role="status"]').count() === 1 && await page.locator('#c-account-scope').getAttribute('aria-busy') === 'true');
    await e().click(); await spend(60); release(); await page.waitForTimeout(100);
    check('late old account response cannot overwrite', await page.locator('#p-now .tile .v').first().textContent() === '60원' && await e().getAttribute('aria-pressed') === 'true');
    await page.unroute(pattern); await company().click(); await spend(100);
    const errPattern = '**/api/naver-auto/clients/11?account_key=' + cfg.e;
    await page.route(errPattern, route => route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'client-not-visible',message:'없거나 볼 수 없는 광고주입니다'})}));
    await e().click(); await page.getByRole('button', {name:'회사 전체 다시 조회',exact:true}).waitFor();
    check('current key error never falls back to company money', await page.locator('#p-now .tile').count() === 0);
    check('error does not keep stale account options', await page.locator('#c-account-scope button').count() === 1);
    check('error ends loading state', await page.locator('#c-account-scope').getAttribute('aria-busy') === 'false');
    await page.unroute(errPattern);
    await page.getByRole('button', {name:'회사 전체 다시 조회',exact:true}).click(); await spend(100);
    check('explicit company recovery works', await company().getAttribute('aria-pressed') === 'true');
    for (const variant of ['legacy metadata missing', 'company metadata', 'different account key']) {
      await page.route(errPattern, async route => {
        const response = await route.fetch({url:cfg.base + '/api/naver-auto/clients/11'});
        const body = await response.json();
        if (variant === 'legacy metadata missing') delete body.account_selection;
        if (variant === 'company metadata') body.account_selection = {kind:'company',account_key:null};
        if (variant === 'different account key') body.account_selection = {kind:'account',account_key:cfg.a};
        await route.fulfill({response,body:JSON.stringify(body)});
      });
      await e().click(); await page.getByRole('button', {name:'회사 전체 다시 조회',exact:true}).waitFor();
      check('mismatched selected response discarded: ' + variant, await page.locator('#p-now .tile').count() === 0 && await page.locator('#c-account-scope').getAttribute('aria-busy') === 'false');
      await page.unroute(errPattern);
      await page.getByRole('button', {name:'회사 전체 다시 조회',exact:true}).click(); await spend(100);
    }
    const companyPattern = '**/api/naver-auto/clients/11';
    await page.route(companyPattern, async route => {
      const response = await route.fetch(); const body = await response.json();
      delete body.account_selection; delete body.account_choices;
      await route.fulfill({response,body:JSON.stringify(body)});
    });
    await routeClient(12); await page.waitForFunction(() => document.getElementById('c-name').textContent === '가게12');
    await routeClient(11); await spend(100);
    check('legacy default company response remains compatible', await company().getAttribute('aria-pressed') === 'true');
    await page.unroute(companyPattern);
    await routeClient(12); await page.waitForFunction(() => document.getElementById('c-name').textContent === '가게12');
    await routeClient(11); await spend(100);
    let releaseOld, oldReceived = false;
    const oldHeld = new Promise(resolve => {releaseOld = resolve;});
    await page.route(pattern, async route => {const response=await route.fetch();oldReceived=true;await oldHeld;await route.fulfill({response});});
    await a().click(); while (!oldReceived) await new Promise(resolve => setTimeout(resolve,10));
    await routeClient(12); await page.waitForFunction(() => document.getElementById('c-name').textContent === '가게12');
    releaseOld(); await page.waitForTimeout(100);
    check('old company response cannot overwrite new route', await page.locator('#c-name').textContent() === '가게12');
    await page.unroute(pattern); await routeClient(11); await spend(100);
    check('returning from another company defaults to company sum', await company().getAttribute('aria-pressed') === 'true');
    check('narrow screen has no horizontal overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    check('no external or script errors', external === 0 && errors.length === 0);
    await context.close();
  } finally {await browser.close();}
  console.log(JSON.stringify(results));process.exitCode=results.every(r => r.pass)?0:1;
})().catch(error => {console.error(error.stack);process.exitCode=1;});
