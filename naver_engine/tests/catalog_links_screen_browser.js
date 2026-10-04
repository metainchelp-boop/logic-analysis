'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const cfg = JSON.parse(process.argv[2]);

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const page = await context.newPage(), errors = [], external = [], writes = [], sessionStatuses = [];
  let code = cfg.staff, entryPending = true;
  let injectedReason = null, injectedSource = null;
  await context.route('**/*', route => {
    if (route.request().url().startsWith(cfg.base + '/')) return route.continue();
    external.push(new URL(route.request().url()).origin); return route.abort();
  });
  await page.route('**/naver/sso-bootstrap.js', route => {
    // 새 전산 입장만 교환한다. 새로고침·화면 이동은 저장된 관제 세션을 재사용한다.
    const body = entryPending ? 'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(' +
      JSON.stringify({code,codeVerifier:'V'.repeat(42)+'A'}) + ')};' :
      'window.__metaincSso={started:false,legacyPresent:false};';
    entryPending = false;
    return route.fulfill({contentType:'application/javascript',body});
  });
  await page.route('**/links/pending**', async route => {
    const response = await route.fetch(), body = await response.json();
    if (injectedReason) body.rows = body.rows.map(row => Object.assign({}, row, {
      can_confirm:false, confirm_block_reason:injectedReason, name:row.name + '<img src=x onerror=alert(1)>'
    }));
    if (injectedSource) Object.assign(body, {source_state:injectedSource, rows:[]});
    await route.fulfill({response, json:body});
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname); });
  page.on('response', response => {
    if (new URL(response.url()).pathname === '/api/naver-auto/session') sessionStatuses.push(response.status());
  });
  try {
    await page.clock.install({time:new Date(cfg.now)});
    await page.goto(cfg.base + '/naver/links?possibility_id=' + cfg.pid);
    // 실제 catalog 응답은 오래된 계약 종료일이 있어도 본인 담당+현재 번호 증명으로 확정 가능하다.
    await page.locator('#linksBody input').waitFor();
    assert.equal(await page.locator('#linksBody').getByRole('button',{name:'이 계정 맞음',exact:true}).count(),1);
    assert.doesNotMatch(await page.textContent('#linksBody'),/계약 종료 후 14일이 지나 연결을 확정할 수 없습니다/);
    injectedReason = 'ended-over-14-days';
    await page.reload();
    await page.locator('#linksBody').getByText(/연결 판정 자료가 이전 기준입니다/).waitFor();
    assert.match(await page.textContent('#linksBody'),/계약 종료 후 경과일만으로 연결을 제외하지 않습니다/);
    assert.equal(await page.locator('#linksBody').getByRole('button',{name:'이 계정 맞음',exact:true}).count(),0);
    assert.equal(await page.locator('#linksBody img').count(),0);
    assert.ok((await page.textContent('#linksBody')).includes('<img src=x onerror=alert(1)>'));
    injectedReason = '<img src=x onerror=alert(2)>';
    await page.reload();
    await page.locator('#linksBody').getByText(/확정 차단 사유를 확인하지 못했습니다/).waitFor();
    assert.equal((await page.textContent('#linksBody')).includes(injectedReason),false);
    assert.equal(await page.locator('#linksBody img').count(),0);
    injectedReason = null; injectedSource = 'accounts-unavailable';
    await page.reload();
    await page.locator('#linksBody').getByText(/이관 계정 목록을 확인할 수 없어/).waitFor();
    assert.equal(await page.locator('#confirmAuto').isVisible(),false);
    injectedSource = null;
    await page.goto(cfg.base + '/naver/transfers');
    const coverage = page.locator('#coverageRows tr').filter({hasText:cfg.company});
    await coverage.getByRole('button',{name:'짝 확인 열기',exact:true}).waitFor();
    assert.deepEqual(sessionStatuses,[200],'직원 새로고침·이동은 최초 로그인 세션을 재사용해야 합니다');
    assert.equal(await page.locator('#coverageRows tr').filter({hasText:cfg.other_company}).count(),0);
    await coverage.getByRole('button',{name:'짝 확인 열기',exact:true}).click();
    await page.waitForURL('**/naver/links?possibility_id=' + cfg.pid);
    await page.locator('#linksBody').getByText(cfg.company,{exact:false}).waitFor();
    assert.equal(await page.locator('#linksBody').getByRole('button',{name:cfg.company,exact:true}).count(),
      cfg.expired_contract ? 1 : 0,
      '기존 전산 업체가 있는 종료계약 fixture는 상세 열기 가능, catalog-only fixture는 상세 버튼 없음');
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

    if (cfg.expired_contract) {
      // 화면으로 진짜 POST까지 증명한다. 권한/번호를 우회하는 응답 주입은 이 단계에 없다.
      await page.goto(cfg.base + '/naver/links?possibility_id=' + cfg.pid);
      await page.locator('#linksBody input').fill(cfg.own);
      const accepted = page.waitForResponse(value => value.url().endsWith('/links/confirm'));
      await page.locator('#linksBody').getByRole('button',{name:'이 계정 맞음',exact:true}).click();
      assert.equal((await accepted).status(),200);
      await page.locator('#linksBody').getByText('사람 확인 「맞음」',{exact:false}).waitFor();
      assert.deepEqual(sessionStatuses,[200]);
      assert.equal(writes.filter(value => value.endsWith('/links/confirm')).length,1);
      assert.ok(writes.every(value => ['/api/naver-auto/session','/api/naver-auto/links/confirm'].includes(value)));
      assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
      console.log('catalog-links-screen-ok');
      return;
    }

    await page.evaluate(() => sessionStorage.clear()); code = cfg.ceo; entryPending = true;
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
    await page.locator('#linksBody').getByRole('button',{name:cfg.other_company,exact:true}).waitFor();
    assert.equal(writes.filter(value => value.endsWith('/links/confirm')).length,2);
    assert.equal(writes.filter(value => value.endsWith('/session')).length,2);
    assert.deepEqual(sessionStatuses,[200,200],'직원·대표 입장에 각각 한 번만 로그인해야 합니다');
    assert.ok(writes.every(value => ['/api/naver-auto/session','/api/naver-auto/links/confirm'].includes(value)));
    assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    console.log('catalog-links-screen-ok');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
