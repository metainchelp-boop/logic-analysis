/* Local synthetic-only diagnostic. Reads real product JS; no product changes or external requests. */
'use strict';
const fs=require('node:fs'), path=require('node:path'), http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'), pageDir=path.join(root,'backend/naver_page');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const now=new Date().toISOString();
let apiLog=[],meDelay=0,accountDelay=0,large=false,nextFault=0,revision=0;
const baseRows=Array.from({length:1789},(_,i)=>({ad_account_no:String(700000+i),account_name:'합성 계정 '+i,
 company_name:'합성 업체 '+i,possibility_id:i+1,mapping:'matched',workflow:'진행중',owner:{name:'합성 담당'},
 collection:{status:'ok',bizmoney:i,checked_at:now},management:{cadence:'daily',excluded:false,can_manage:false,can_collect:false}}));
const coverage=Array.from({length:450},(_,i)=>({possibility_id:i+1,company_name:'합성 업체 '+i,workflow:'진행중',
 owner:{name:'합성 담당'},state:'matched',matched_account_count:1,candidate_count:1}));
function inv(selection='all'){return {selection,rows:large?baseRows.map(r=>({...r,synthetic_padding:'X'.repeat(7200)})):baseRows,
 total:1789,counts:{matched:1789,no_erp_record:0,unclassified:0},accounts_current:true,matching_ready:true,
 catalog_status:'accepted',accounts_at:now,catalog_at:now,
 managed_coverage:{ready:true,total:450,matched:450,missing:0,items:coverage}};}
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname.startsWith('/api/naver-auto/')){
  const entry={path:u.pathname,method:req.method,at:performance.now(),cursor:u.searchParams.get('view_cursor'),aborted:false};apiLog.push(entry);
  res.on('close',()=>{if(!res.writableFinished)entry.aborted=true;});
  let body={};
  if(u.pathname.endsWith('/me')){await sleep(meDelay);body={idx:1,name:'합성 대표',scope:'ALL',owner_verification:true,verified_linking:true,people:[]};}
  else if(u.pathname.endsWith('/accounts')){
   const fault=nextFault;nextFault=0;await sleep(accountDelay);
   if(fault){entry.responded=performance.now();if(!res.destroyed){res.writeHead(fault,{'content-type':'application/json'});res.end(JSON.stringify({error:fault===403?'org-stale':'unavailable'}));}return;}
   body={version:1,checked_at:now,cursor:'synthetic_cursor_'+revision,base_cursor:null,mode:'full',data:inv(u.searchParams.get('selection')||'all'),rows:null};
   if(entry.cursor===body.cursor)body={...body,mode:'unchanged',base_cursor:entry.cursor,data:null};
  }else if(u.pathname.endsWith('/links/pending'))body={rows:[],decisions:[],source:'catalog',source_state:'accepted'};
  else if(u.pathname.endsWith('/health'))body={runtime:{state:'unavailable',indicator:'red',reason_code:'UNAVAILABLE',verified_at:null,valid_for_seconds:0}};
  else if(u.pathname.endsWith('/board'))body={rows:[],band:{},counts:{},selection:'all'};
  else if(u.pathname.endsWith('/dashboard'))body={rows:[],period:{},accounts:{},coverage:{},selection:'all'};
  else if(u.pathname.endsWith('/reports'))body={rows:[],selection:'all'};
  entry.responded=performance.now();const raw=JSON.stringify(body);entry.bytes=Buffer.byteLength(raw);
  if(!res.destroyed){res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});res.end(raw);}return;
 }
 let name=u.pathname.slice('/naver/'.length);
 if(name==='sso-bootstrap.js'){res.writeHead(200,{'content-type':'application/javascript'});res.end('window.__metaincSso=null;');return;}
 if(!['app.js','app.css','report-ui.js','report-pdf.js'].includes(name))name='index.html';
 res.writeHead(200,{'content-type':name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 res.end(fs.readFileSync(name==='app.js'&&process.env.NAVER_NAVIGATION_APP?process.env.NAVER_NAVIGATION_APP:path.join(pageDir,name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
 const chrome=process.env.NAVER_CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':null);
 const browser=await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
 const ctx=await browser.newContext({locale:'ko-KR',timezoneId:'Asia/Seoul'}),page=await ctx.newPage();
 page.setDefaultTimeout(5000);
 const errors=[],external=[],checks=[],metrics={};page.on('pageerror',e=>errors.push(e.message));
 await ctx.route('**/*',r=>{if(r.request().url().startsWith(base+'/'))return r.continue();external.push(r.request().url());return r.abort();});
 await page.addInitScript(()=>sessionStorage.setItem('naverWatch.session',JSON.stringify({token:'synthetic',exp:Date.now()+3600000})));
 async function current(){await page.waitForFunction(()=>document.querySelector('#inventorySync').dataset.status==='current');}
 async function check(name,fn){try{await fn();checks.push({name,result:'PASS'});}catch(e){checks.push({name,result:'FAIL',message:e.message});accountDelay=0;nextFault=0;await page.goto(base+'/naver/transfers');await current();}}
 try{
  const accounts=()=>apiLog.filter(x=>x.path.endsWith('/accounts'));
  const nav=()=>page.locator('.menu [data-go="/naver/transfers"]');
  await page.goto(base+'/naver/transfers');await current();
  await check('panel-switch-revalidates-before-reveal',async()=>{
   accountDelay=250;const before=accounts().length;
   await page.click('#inventoryAccountsTab');
   assert.equal(await page.locator('#inventoryCard').isVisible(),false);
   assert.equal(await page.locator('#managedCoverage').isVisible(),false);
   await current();assert.equal(accounts().length-before,1);
   assert.equal(await page.locator('#inventoryCard').isVisible(),true);
  });
  await check('same-route-in-flight-clicks-coalesce',async()=>{
   accountDelay=500;const before=accounts().length,links=apiLog.filter(x=>x.path.endsWith('/links/pending')).length;
   await nav().click();await nav().click();await nav().click();await current();
   assert.equal(accounts().length-before,1);
   assert.equal(apiLog.filter(x=>x.path.endsWith('/links/pending')).length-links,1);
  });
  await check('failure-releases-deduped-request-for-retry',async()=>{
   accountDelay=200;nextFault=503;const before=accounts().length;
   await nav().click();await nav().click();
   await page.waitForTimeout(40);assert.equal(accounts().length-before,1);
   await page.waitForFunction(()=>['error','stale'].includes(document.querySelector('#inventorySync').dataset.status));
   assert.equal(accounts().length-before,1);await nav().click();await current();assert.equal(accounts().length-before,2);
  });
  await check('explicit-refresh-still-refetches-and-coalesces-in-flight',async()=>{
   accountDelay=200;const before=accounts().length;await page.click('#inventoryReload');await page.click('#inventoryReload');await current();
   assert.equal(accounts().length-before,1);await page.click('#inventoryReload');await current();assert.equal(accounts().length-before,2);
  });
  await check('obsolete-view-request-aborted',async()=>{
   accountDelay=1000;const before=accounts().length;
   await page.click('#inventoryReload');await page.waitForTimeout(60);await page.locator('.menu [data-go="/naver/dashboard"]').click();
   await page.waitForTimeout(80);assert.equal(accounts().length-before,1);assert.equal(accounts().at(-1).aborted,true);
   accountDelay=0;await nav().click();await current();
  });
  await check('scope-change-aborts-and-purges-old-data',async()=>{
   accountDelay=700;await page.click('#inventoryReload');await page.waitForTimeout(60);const old=accounts().at(-1);
   await page.selectOption('#scope','me');assert.equal(await page.locator('#inventoryRows').innerText(),'');
   await current();assert.equal(old.aborted,true);accountDelay=0;await page.selectOption('#scope','all');await current();
  });
  await check('hidden-tab-aborts-and-return-revalidates',async()=>{
   accountDelay=700;await page.click('#inventoryReload');await page.waitForTimeout(60);const old=accounts().at(-1);
   await page.evaluate(()=>{window.__testVisibility='hidden';Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.__testVisibility});document.dispatchEvent(new Event('visibilitychange'));});
   await page.waitForTimeout(60);assert.equal(old.aborted,true);
   assert.equal(await page.locator('#s-transfers.view-unverified').count(),1);
   const before=accounts().length;accountDelay=0;
   await page.evaluate(()=>{window.__testVisibility='visible';document.dispatchEvent(new Event('visibilitychange'));});
   await current();assert.equal(accounts().length-before,1);
  });
  await check('authority-failure-purges-both-panels-and-retry-works',async()=>{
   nextFault=403;await page.click('#inventoryCoverageTab');
   await page.waitForFunction(()=>document.querySelector('#inventorySync').dataset.status==='error');
   assert.equal(await page.locator('#inventoryRows').innerText(),'');assert.equal(await page.locator('#coverageRows').innerText(),'');
   assert.equal(await page.locator('#inventoryCard').isVisible(),false);assert.equal(await page.locator('#managedCoverage').isVisible(),false);
   await page.locator('#inventorySync button').click();await current();
  });
  await check('changed-server-edition-refreshes-visible-content',async()=>{
   revision++;baseRows[0].account_name='정정된 합성 계정';await page.click('#inventoryReload');await current();
   assert.match(await page.locator('#inventoryRows').innerText(),/정정된 합성 계정/);
  });
  await check('large-cache-cap-remains-bounded',async()=>{
   large=true;apiLog=[];await page.goto(base+'/naver/transfers');await current();
   await page.click('#inventoryReload');await current();assert.equal(accounts().at(-1).cursor,null);
   metrics.large_repeat_bytes=accounts().at(-1).bytes;
  });
  await check('no-external-or-browser-errors',()=>{assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.equal(apiLog.filter(x=>x.method!=='GET').length,0);});
  const result={at:new Date().toISOString(),environment:'installed Chrome, synthetic API delays/1789 accounts/450 companies; no live API',metrics,checks,errors,external_requests:external.length};
  if(process.env.NAVER_NAVIGATION_RESULT)fs.writeFileSync(process.env.NAVER_NAVIGATION_RESULT,JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));process.exitCode=checks.some(x=>x.result==='FAIL')?1:0;
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
