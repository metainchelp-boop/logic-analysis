'use strict';
// 실제 화면 파일 + loopback 합성 HTTP 응답. 운영·네이버·전산 자격 API에는 접속하지 않는다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const test = require('node:test');
const pageRoot = path.join(__dirname, '../backend/naver_page');
function row(id, balance, extra={}) {
  return Object.assign({ad_account_no:String(id),account_name:'합성 계정 '+id,company_name:'합성 업체',
    possibility_id:51,mapping:'matched',workflow:'진행중',owner:{name:'합성 담당'},management:{cadence:'daily'},
    collection:{bizmoney:balance,bizmoney_at:'2026-10-03T09:00:00+09:00',stale:id===704}},extra);
}
async function fixtureServer() {
  const fixture = {mode:'ok',requests:[],rows:[row(700,null),row(701,0),row(702,-3),row(703,0.29),row(704,0.71),
    row(705,10),row(706,10)],revision:0};
  const coverage = {ready:true,total:3,matched:1,missing:2,items:[
    {possibility_id:51,company_name:'Alpha   합성 업체',workflow:'전략관리',owner:{name:'Kim 담당'},state:'candidate_pending',codes:['ID_MISSING'],matched_account_count:0,candidate_count:1},
    {possibility_id:52,company_name:'Beta 합성 업체',workflow:'진행중',owner:{name:'Lee 담당'},state:'matched',codes:[],matched_account_count:1,candidate_count:1},
    {possibility_id:53,company_name:'Gamma 합성 업체',workflow:'사후관리',owner:{name:'Park 담당'},state:'id_missing',codes:['ID_MISSING'],matched_account_count:0,candidate_count:0}]};
  const server = http.createServer((req,res) => {
    const url = new URL(req.url,'http://127.0.0.1');
    function send(status,body,type='application/json') {res.writeHead(status,{'Content-Type':type,'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
      'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"});res.end(body);}
    if (url.pathname.startsWith('/api/')) {
      fixture.requests.push({url:req.url,method:req.method});
      if (req.method !== 'GET') return send(405,'{}');
      if (url.pathname.endsWith('/me')) return send(200,JSON.stringify({idx:1,scope:'ALL',name:'합성 대표',owner_verification:true,people:[{idx:2,name:'합성 담당',active:true,account_count:1}]}));
      if (url.pathname.endsWith('/accounts')) {
        if (fixture.mode==='network') return send(503,'{"error":"unavailable"}');
        if (fixture.mode==='denied') return send(403,'{"error":"not-visible"}');
        if (fixture.mode==='logout') return send(401,'{"error":"session-ended"}');
        if (fixture.mode==='invalid-json') return send(200,'{"rows":[{"collection":{"bizmoney":NaN}}]}');
        let rows=fixture.rows;
        if (url.searchParams.get('selection')==='person:2') rows=rows.slice(0,1);
        if (url.searchParams.get('mapping')==='unclassified') rows=[];
        if (url.searchParams.get('workflow')==='전략관리') rows=rows.slice(3,5);
        if (url.searchParams.get('view')==='lost') rows=[row(799,null)];
        const data={selection:url.searchParams.get('selection'),rows,total:fixture.rows.length,view:url.searchParams.get('view'),
          counts:{matched:7,no_erp_record:0,unclassified:0},accounts_current:true,matching_ready:fixture.mode!=='source',catalog_status:'accepted',
          summary:{ready:fixture.mode!=='source',current_total:7,lost_count:1,balance:{known_sum:18,known_count:6,total_count:7}},
          managed_coverage:Object.assign({},coverage,{ready:fixture.mode!=='source'})};
        const cursor='synthetic_'+fixture.revision;
        return send(200,JSON.stringify({version:1,mode:url.searchParams.get('view_cursor')===cursor?'unchanged':'full',
          cursor,base_cursor:url.searchParams.get('view_cursor')===cursor?cursor:null,checked_at:new Date().toISOString(),
          data:url.searchParams.get('view_cursor')===cursor?null:data,rows:null}).replace(/"NONFINITE"/g,'1e999'));
      }
      if (url.pathname.endsWith('/board')) return send(200,JSON.stringify({rows:[],counts:{},band:{runs:[]},done_rows:[]}));
      return send(404,'{}');
    }
    if (url.pathname==='/naver/sso-bootstrap.js') return send(200,"sessionStorage.setItem('naverWatch.session',JSON.stringify({token:'synthetic-only',exp:Date.now()+3600000}));",'application/javascript');
    const filename=['/naver/app.js','/naver/app.css'].includes(url.pathname) ? path.basename(url.pathname) :
      /^\/naver\/(?:transfers|issues)?$/.test(url.pathname)?'index.html':null;
    if (!filename) return send(404,'');
    return send(200,fs.readFileSync(path.join(pageRoot,filename)),filename.endsWith('.js')?'application/javascript':filename.endsWith('.css')?'text/css':'text/html');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  fixture.base='http://127.0.0.1:'+server.address().port;
  fixture.close=()=>new Promise(resolve=>server.close(resolve));
  return fixture;
}

if (process.argv.includes('--serve')) {
  fixtureServer().then(fixture=>console.log(JSON.stringify({url:fixture.base+'/naver/transfers',data:'합성 시험 자료만 사용',store:'없음'})));
} else test('합성 브라우저: 잔액·필터·검색·안전 진입·권한·반응형 경계', async () => {
  const {chromium}=require('playwright');
  const browser=await chromium.launch(process.env.NAVER_SCREEN_CHROMIUM ? {executablePath:process.env.NAVER_SCREEN_CHROMIUM} : {});
  const fixture=await fixtureServer();
  const context=await browser.newContext({locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const errors=[],external=[];
  await context.route('**/*',route=>{
    if (route.request().url().startsWith(fixture.base+'/')) return route.continue();
    if (route.request().url()==='http://metainc.co.kr/metapos/advertiser-setup?company=51&panel=credentials&vendor=naver') {
      external.push({url:route.request().url(),headers:route.request().headers()});
      return route.fulfill({contentType:'text/html',body:'<!doctype html><p>합성 전산 로그인 안내</p>'});
    }
    external.push({unexpected:route.request().url()}); return route.abort();
  });
  const page=await context.newPage(); page.on('pageerror',error=>errors.push(error.message));
  async function reload() {await page.click('#inventoryReload');await page.waitForSelector('#inventorySync[data-status="current"]');}
  try {
    await page.goto(fixture.base+'/naver/transfers'); await page.waitForSelector('#inventorySync[data-status="current"]');
    await page.fill('#coverageSearch','  KIM 담당 ');
    assert.equal(await page.textContent('#coverageSearchStatus'),'검색 결과 1 / 3업체');
    assert.match(await page.textContent('#coverageStatus'),/실관리 3/);
    const popupPromise=context.waitForEvent('page');
    await page.getByRole('button',{name:'광고 계정 ID 입력',exact:true}).click();
    const popup=await popupPromise; await popup.waitForLoadState();
    assert.equal(await popup.evaluate(()=>window.opener),null);
    assert.equal(external[0].headers.referer,undefined); assert.equal(external[0].headers.authorization,undefined);
    await popup.close();
    await page.evaluate(()=>{window.open=()=>null;});
    await page.getByRole('button',{name:'광고 계정 ID 입력',exact:true}).click();
    assert.match(await page.textContent('#toast'),/직접 열기/);
    await page.click('#inventoryAccountsTab'); await page.waitForSelector('#inventorySync[data-status="current"]');
    assert.deepEqual(await page.locator('#inventoryRows tr[data-account]').evaluateAll(rows=>rows.map(row=>row.dataset.account)),['705','706','704','703','701','702','700']);
    assert.match(await page.textContent('#inventoryBalance'),/합계 : 18원.*확인 6 \/ 7계정.*이전 확인값 포함/);
    await page.locator('#inventorySearch').focus();
    await page.evaluate(()=>{window.retainedRow=document.querySelector('[data-account="705"]');});
    await reload();
    assert.equal(await page.evaluate(()=>window.retainedRow===document.querySelector('[data-account="705"]')),true);
    await page.selectOption('#inventoryWorkflow','전략관리'); await page.waitForSelector('#inventorySync[data-status="current"]');
    assert.match(await page.textContent('#inventoryBalance'),/합계 : 1원.*확인 2 \/ 2계정/);
    await page.fill('#inventorySearch','703'); assert.match(await page.textContent('#inventoryBalance'),/합계 : 0원.*확인 1 \/ 1계정/);
    await page.fill('#inventorySearch','없는계정'); assert.match(await page.textContent('#inventoryBalance'),/합계 : 0원.*대상 계정 없음/);
    await page.fill('#inventorySearch',''); await page.selectOption('#inventoryWorkflow','all'); await reload();
    await page.selectOption('#inventoryView','lost'); await page.waitForSelector('#inventorySync[data-status="current"]');
    assert.match(await page.textContent('#inventoryBalance'),/합계 : —.*확인 잔액 없음/);
    await page.selectOption('#inventoryView','current'); await reload();
    fixture.mode='network'; await page.click('#inventoryReload'); await page.waitForSelector('#inventorySync[data-status="stale"]');
    assert.match(await page.textContent('#inventoryBalance'),/18원/); assert.match(await page.textContent('#inventorySync'),/이전 확인 자료/);
    fixture.mode='source'; fixture.revision++; await reload(); assert.match(await page.textContent('#inventoryBalance'),/합계 : —.*집계 보류/);
    assert.equal(await page.getByRole('button',{name:'광고 계정 ID 입력',exact:true}).count(),0);
    fixture.mode='ok';fixture.revision++;await reload();
    const originalRows=fixture.rows;
    fixture.rows=[row(800,'100'),row(801,true),row(802,'NONFINITE'),row(803,Number.MAX_SAFE_INTEGER+1)];fixture.revision++;await reload();
    assert.match(await page.textContent('#inventoryBalance'),/확인 잔액 없음.*확인 0 \/ 4계정/);
    fixture.mode='invalid-json';await page.click('#inventoryReload');await page.waitForSelector('#inventorySync[data-status="stale"]');
    assert.match(await page.textContent('#inventoryBalance'),/확인 잔액 없음/);
    fixture.mode='ok';fixture.rows=[row(800,Number.MAX_SAFE_INTEGER),row(801,1)];fixture.revision++;await reload();
    assert.match(await page.textContent('#inventoryBalance'),/안전한 표시 범위 초과/);
    fixture.rows=originalRows;fixture.revision++;await reload();
    for (const width of [320,390,820,1280,1440]) {
      await page.setViewportSize({width,height:900});
      for (const panel of ['inventoryAccountsTab','inventoryCoverageTab']) {
        await page.click('#'+panel); await page.waitForSelector('#inventorySync[data-status="current"]');
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${width} ${panel} 가로 넘침`);
      }
    }
    if(process.env.NAVER_SCREEN_SHOTS){fs.mkdirSync(process.env.NAVER_SCREEN_SHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.NAVER_SCREEN_SHOTS,'transfer-coverage.png'),fullPage:true});}
    assert.equal(await page.inputValue('#coverageSearch'),'  KIM 담당 ');
    await page.selectOption('#scope','person:2');await page.waitForSelector('#inventorySync[data-status="current"]');
    assert.equal(await page.inputValue('#coverageSearch'),'');assert.match(await page.textContent('#inventoryBalance'),/확인 잔액 없음/);
    fixture.mode='denied';await page.click('#inventoryReload');await page.waitForSelector('#inventorySync[data-status="error"]');
    assert.equal(await page.textContent('#inventoryBalance'),'');assert.equal(await page.textContent('#coverageRows'),'');
    fixture.mode='ok';await page.locator('#inventorySync button').click();await page.waitForSelector('#inventorySync[data-status="current"]');
    await page.fill('#coverageSearch','Alpha');fixture.mode='logout';await page.click('#inventoryReload');await page.waitForSelector('#s-blocked.on');
    assert.equal(await page.textContent('#inventoryBalance'),'');assert.equal(await page.inputValue('#coverageSearch'),'');
    assert.deepEqual(errors,[]);assert.equal(external.length,1);assert.ok(fixture.requests.every(request=>request.method==='GET'));
    console.log('transfer-balance-screen-ok: 5 widths, decimal totals, popup isolated, auth cleared, no writes');
  } finally {await context.close();await browser.close();await fixture.close();}
});
