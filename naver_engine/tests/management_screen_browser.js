'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require('playwright');
const {auditFluidScreens}=require('./fluid_screen_audit');
const cfg=JSON.parse(process.argv[2]);
(async()=>{
  const browser=await chromium.launch();
  const context=await browser.newContext({locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const page=await context.newPage(), errors=[],external=[],writes=[];
  let code=cfg.ceo;
  await context.route('**/*',route=>{
    if(route.request().url().startsWith(cfg.base+'/'))return route.continue();
    external.push(route.request().url());return route.abort();
  });
  await page.route('**/naver/sso-bootstrap.js',route=>route.fulfill({contentType:'application/javascript',
    body:'window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve('+JSON.stringify({code,codeVerifier:'V'.repeat(42)+'A'})+')};'}));
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST')writes.push(new URL(r.url()).pathname);});
  async function showAccounts(){
    await page.waitForFunction(()=>document.querySelector('#inventorySync').dataset.status==='current');
    assert.equal(await page.locator('#managedCoverage').isVisible(),true);
    assert.equal(await page.locator('#inventoryCard').isVisible(),false);
    await page.click('#inventoryAccountsTab');
    await page.waitForFunction(()=>document.querySelector('#inventorySync').dataset.status==='current');
    assert.equal(await page.locator('#managedCoverage').isVisible(),false);
    assert.equal(await page.locator('#inventoryCard').isVisible(),true);
  }
  try{
    if(cfg.shots)fs.mkdirSync(cfg.shots,{recursive:true});
    await page.clock.install({time:new Date(cfg.now)});
    await page.goto(cfg.base+'/naver/transfers');
    await showAccounts();
    const own=page.locator('#inventoryRows tr').filter({hasText:cfg.own});
    await own.getByText('자동 수집 대상입니다.',{exact:false}).waitFor();
    assert.equal(await own.getByRole('button',{name:'관제 제외',exact:true}).count(),0);
    assert.equal(await own.getByRole('button',{name:'관제 포함',exact:true}).count(),0);
    await own.locator('summary').filter({hasText:'광고 상태·사유'}).click();
    await own.getByText('저장된 광고 상태 응답이 없습니다.',{exact:false}).waitFor();
    assert.equal(await own.getByRole('button',{name:'다음 사유',exact:true}).count(),0);
    assert.equal(writes.filter(p=>p.endsWith('/management/update')).length,0);
    assert.equal(await own.getByRole('button',{name:'지금 조회',exact:true}).isVisible(),false);
    await own.locator('details.collection-recovery > summary').click();
    await own.getByRole('button',{name:'지금 조회',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('조회 요청'));
    assert.equal(writes.filter(p=>p.endsWith('/management/collect')).length,1);
    await page.getByRole('button',{name:'📄 보고서',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#reportsSchedule').textContent.includes('매월 3일'));
    assert.match(await page.textContent('#reportsRows'),/아직 생성되지 않음|연결된 실관리 광고 계정이 없습니다/);
    if(cfg.shots)await page.screenshot({path:path.join(cfg.shots,'실관리-보고서-대기.png'),fullPage:true});
    const beforeAuditWrites=writes.length;
    await auditFluidScreens(page,cfg);
    assert.equal(writes.length,beforeAuditWrites,'fluid audit must not send writes');
    await page.evaluate(()=>sessionStorage.clear());code=cfg.staff;
    await page.goto(cfg.base+'/naver/transfers');
    await showAccounts();
    await own.getByText('자동 수집 대상입니다.',{exact:false}).waitFor();
    assert.equal(await own.getByRole('button',{name:'관제 제외',exact:true}).count(),0);
    assert.equal(await own.getByRole('button',{name:'지금 조회',exact:true}).count(),0);
    assert.equal(await own.getByRole('button',{name:'기간 재확인',exact:true}).count(),0);
    assert.equal(await page.locator('#inventoryRows tr').filter({hasText:cfg.other}).count(),0);
    assert.equal(await page.locator('#collectionControls').isVisible(),false);
    if(cfg.shots)await page.screenshot({path:path.join(cfg.shots,'실관리-직원-본인범위.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    assert.ok(writes.every(p=>['/api/naver-auto/session','/api/naver-auto/management/collect'].includes(p)));
    console.log('management-screen-ok');
  }finally{await context.close();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
