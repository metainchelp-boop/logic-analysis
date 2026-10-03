'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const page = await context.newPage(), errors = [], external = [], writes = [];
  let code = cfg.staff;
  await context.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(new URL(route.request().url()).origin); return route.abort();
  });
  await page.route('**/naver/sso-bootstrap.js', route => route.fulfill({contentType:'application/javascript',
    body:'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
      JSON.stringify({code,codeVerifier:'V'.repeat(42)+'A'}) + ')};'}));
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname); });
  try {
    await page.clock.install({time:new Date(cfg.now)});
    await page.goto(cfg.base + '/naver/transfers');
    const coverage = page.locator('#coverageRows tr').filter({hasText:cfg.company});
    await coverage.getByRole('button',{name:'짝 확인 열기',exact:true}).waitFor();
    assert.equal(await page.locator('#coverageRows tr').filter({hasText:cfg.other_company}).count(),0);
    await coverage.getByRole('button',{name:'짝 확인 열기',exact:true}).click();
    await page.waitForURL('**/naver/links?possibility_id=' + cfg.pid);
    await page.locator('#linksBody').getByText(cfg.company,{exact:false}).waitFor();
    assert.equal(await page.locator('#linksBody').getByRole('button',{name:cfg.company,exact:true}).count(),0);
    assert.equal((await page.textContent('#linksBody')).includes(cfg.other_company),false);
    assert.match(await page.textContent('#linksFilter'),/선택한 전산 업체/);
    assert.equal(await page.locator('#confirmAuto').isVisible(),false);
    await page.goBack();
    await coverage.getByRole('button',{name:'짝 확인 열기',exact:true}).waitFor();
    await coverage.getByRole('button',{name:'짝 확인 열기',exact:true}).click();
    await page.locator('#linksBody input').waitFor();
    await page.click('#linksShowAll');
    await page.waitForURL('**/naver/links');
    await page.locator('#linksBody input').waitFor();
    assert.equal((await page.textContent('#linksBody')).includes(cfg.other_company),false);
    assert.equal(writes.filter(value => value.endsWith('/links/confirm')).length,0);

    await page.evaluate(() => sessionStorage.clear()); code = cfg.ceo;
    await page.goto(cfg.base + '/naver/links?possibility_id=' + cfg.pid);
    await page.locator('#linksBody input').waitFor();
    assert.equal((await page.textContent('#linksBody')).includes(cfg.other_company),false);
    assert.equal(await page.locator('#linksBody').getByRole('button',{name:cfg.company,exact:true}).count(),0);
    await page.locator('#linksBody input').fill('1');
    let response = page.waitForResponse(value => value.url().endsWith('/links/confirm'));
    await page.locator('#linksBody').getByRole('button',{name:'이 계정 맞음',exact:true}).click();
    assert.equal((await response).status(),409);
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('광고 계정 ID'));
    await page.waitForFunction(() => {
      const proof = document.querySelector('#linksBody input');
      return proof && proof.value === '';
    });
    if (cfg.shots) {
      fs.mkdirSync(cfg.shots,{recursive:true});
      await page.setViewportSize({width:390,height:844});
      await page.screenshot({path:path.join(cfg.shots,'catalog-업체제한-확인.png'),fullPage:true});
    }
    await page.locator('#linksBody input').fill(cfg.own);
    response = page.waitForResponse(value => value.url().endsWith('/links/confirm'));
    await page.locator('#linksBody').getByRole('button',{name:'이 계정 맞음',exact:true}).click();
    assert.equal((await response).status(),200);
    await page.locator('#linksBody').getByText('사람 확인 「맞음」',{exact:false}).waitFor();
    assert.equal(await page.locator('#linksBody').getByRole('button',{name:cfg.company,exact:true}).count(),0);
    await page.click('#linksShowAll');
    await page.locator('#linksBody').getByText(cfg.other_company,{exact:false}).waitFor();
    assert.equal(writes.filter(value => value.endsWith('/links/confirm')).length,2);
    assert.ok(writes.every(value => ['/api/naver-auto/session','/api/naver-auto/links/confirm'].includes(value)));
    assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    console.log('catalog-links-screen-ok');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
