'use strict';
// Real report renderer and CSS with synthetic in-memory API replies only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {chromium} = require('playwright');
const source = fs.readFileSync('naver_engine/tests/report_ui_model_test.js', 'utf8');
const fixtureBox = {};
vm.runInNewContext(source.slice(source.indexOf('function listData()'), source.indexOf('function findButton(')) +
  source.slice(source.indexOf('function expandedData()'), source.indexOf('function allNodes(')), fixtureBox);
const report = fixtureBox.expandedData();
report.company_name = '합성 검증 업체 <img src=x onerror=alert(1)>';
report.annotations.state='approved'; report.annotations.author={actor:0,at:'2026-09-28T10:00:00+09:00'};
report.annotations.approved_by=0; report.annotations.approved_at='2026-09-28T11:00:00+09:00';
report.annotations.history.items=[{version:1,state:'approved',author:report.annotations.author,approved_by:0,approved_at:report.annotations.approved_at,document:{internal_note:'HISTORY_PRIVATE',client_feedback:'QUESTION_PRIVATE',shared_comment:'과거 공유 코멘트'}}];
report.annotations.shared={version:1,state:'approved',metadata:report.annotations.metadata,shared_comment:'승인 문안 <svg onload=alert(2)>',next_plan:'검토 후 진행할 계획',plan_due:null,targets:{},approved_at:report.annotations.approved_at};
report.payload.details.daily=[1,2,3].map(n=>({day:'2026-09-'+(20+n),totals:{spend:100,clicks:20,impressions:500,conversions:10,conversion_value:500},ratios:{roas:500,cpa:10},coverage:{basic_complete:true,conversion_complete:n!==2}}));
const css = fs.readFileSync('backend/naver_page/app.css','utf8'), script = fs.readFileSync('backend/naver_page/report-ui.js','utf8');

(async () => {
  const browser = await chromium.launch({headless:true,...(process.env.NAVER_REPORT_BROWSER ? {executablePath:process.env.NAVER_REPORT_BROWSER} : {})});
  try {
    for (const width of [320,1920]) {
      const page = await browser.newPage({viewport:{width,height:1000}}), errors=[];
      page.on('pageerror', error=>errors.push(error.message));
      await page.route('**/*',route=>route.abort());
      await page.setContent('<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main class="main"><section id="s-reports"><div id="reportFilters" class="card nr-filters"></div><div id="reportsSource"></div><div id="reportUnlinked"></div><div id="reportsRows"></div><div id="reportsPages"></div><div id="reportsSchedule"></div><div id="reportsStatus"></div><div id="reportDetail"></div></section></main></body></html>');
      await page.addStyleTag({content:css}); await page.addScriptTag({content:script});
      await page.evaluate(async ({report,list})=>{
        function h(tag,attrs,...children) {
          const element=document.createElement(tag);
          for (const [key,value] of Object.entries(attrs||{})) {
            if (value===false || value==null) continue;
            if (key.startsWith('on')) element.addEventListener(key.slice(2),value);
            else element.setAttribute(key,value===true?'':String(value));
          }
          function add(child) { if(child===false || child==null)return;if(Array.isArray(child))child.forEach(add);else element.appendChild(typeof child==='object'?child:document.createTextNode(String(child))); }
          children.forEach(add); return element;
        }
        function put(element,...children) { element.replaceChildren(); const holder=h('div',null,...children); while(holder.firstChild)element.appendChild(holder.firstChild); }
        window.reportRequests=[];
        window.testReportUI=window.NaverReports.create({h,put,$:id=>document.getElementById(id),num:n=>n==null?'—':String(n),won:n=>Math.trunc(n).toLocaleString('ko-KR')+'원',periodText:(a,b)=>a+'~'+b,datedTime:t=>t||'미보관',
          context:()=> 'fixed',active:()=>true,selection:()=> 'all',onList(){},onDetailVerified(){},validation:()=>null,changes:()=>null,denied:()=>false,purge(){},go(){},toast(){},
          fetchList:(path,apply)=>{window.reportRequests.push(path);apply(list);return Promise.resolve();},api:(method,path)=>{window.reportRequests.push(path);if(method!=='GET'||!path.startsWith('/reports/detail?'))throw new Error('unexpected API');return Promise.resolve(structuredClone(report));}});
        await window.testReportUI.load(); document.querySelector('#reportsRows button').click();
      },{report:JSON.parse(JSON.stringify(report)),list:JSON.parse(JSON.stringify(fixtureBox.listData()))});
      await page.waitForSelector('.nr-metric-table');
      assert.equal(await page.locator('.nr-metric-table tbody tr').count(),17);
      assert.equal(await page.locator('.nr-quality-card').count(),3);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'page overflow at '+width);
      assert.equal(await page.locator('img,svg[onload],script[src]').count(),0,'plain text XSS');
      const requests=await page.evaluate(()=>window.reportRequests.length);
      await page.getByRole('button',{name:'ROAS',exact:true}).click();
      assert.equal(await page.locator('#reportChart .nr-dot').count(),2);
      await page.locator('#reportSharePreview').click();
      assert.equal(await page.evaluate(()=>window.reportRequests.length),requests,'local tabs should not request data');
      assert.equal(await page.locator('textarea').count(),0);
      const shared=await page.locator('#reportDetail').innerText();
      assert.ok(shared.includes('승인 문안 <svg onload=alert(2)>'));
      assert.ok(!shared.includes('PRIVATE')); assert.ok(!shared.includes('당시 내부 메모'));
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'shared overflow at '+width);
      assert.deepEqual(errors,[]);
      await page.close();
      console.log('report enrichment browser: '+width+'px PASS; 17 metrics, quality, XSS, partial chart, shared privacy, no tab requests');
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
