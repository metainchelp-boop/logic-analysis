'use strict';
// Only intercepted, synthetic same-origin documents; --write-pdfs explicitly authors three QA artifacts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {chromium} = require('playwright');
assert.ok(process.argv.slice(2).every(arg=>arg==='--write-pdfs'),'only --write-pdfs is accepted');
const writePDFs=process.argv.includes('--write-pdfs');
const product=path.resolve(__dirname,'../..'), artifacts=path.resolve(product,'../../outputs');
const fixtureSource=fs.readFileSync(path.join(__dirname,'report_ui_model_test.js'),'utf8'), fixtureBox={};
vm.runInNewContext(fixtureSource.slice(fixtureSource.indexOf('function listData()'),fixtureSource.indexOf('function findButton('))+
  fixtureSource.slice(fixtureSource.indexOf('function expandedData()'),fixtureSource.indexOf('function allNodes(')),fixtureBox);
const report=fixtureBox.expandedData();
report.company_name='가상 광고주 · 보고서 디자인 PDF 검증';report.revision_fingerprint='a'.repeat(64);
report.status='partial';report.payload.status='partial';
report.annotations.state='approved';report.annotations.metadata.revision_fingerprint=report.revision_fingerprint;
report.annotations.document.internal_note='PRIVATE_EDITOR_NOTE';report.annotations.document.client_feedback='PRIVATE_CUSTOMER_QUESTION';
report.annotations.history={items:[{document:{internal_note:'PRIVATE_HISTORY_NOTE'}}]};
report.annotations.shared={version:report.annotations.version,state:'approved',metadata:structuredClone(report.annotations.metadata),
  shared_comment:'합성 검증용 승인 코멘트입니다. 수치는 실제 매출이 아니며 전환 원인을 확정하지 않습니다.',
  next_plan:'다음 주 소재 두 안의 CTR·CVR을 비교하고, 월간 키워드 전환 확인 후 예산 배분을 검토합니다.',
  plan_due:null,targets:{},approved_at:'2026-10-04T10:30:00+09:00'};
const routes={
  '/app.css':{contentType:'text/css; charset=utf-8',body:fs.readFileSync(path.join(product,'backend/naver_page/app.css'),'utf8')},
  '/report-ui.js':{contentType:'text/javascript; charset=utf-8',body:fs.readFileSync(path.join(product,'backend/naver_page/report-ui.js'),'utf8')},
  '/report-pdf.js':{contentType:'text/javascript; charset=utf-8',body:fs.readFileSync(path.join(product,'backend/naver_page/report-pdf.js'),'utf8')},
  '/':{contentType:'text/html; charset=utf-8',body:'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><script src="/report-ui.js" defer></script><script src="/report-pdf.js" defer></script></head><body><main id="editor" class="nr-internal-review"><section class="nr-annotations"><textarea id="reportNote-internal_note">PRIVATE_OUTSIDE_EDITOR</textarea><textarea id="reportNote-client_feedback">PRIVATE_CUSTOMER_QUESTION</textarea><div id="reportNotesCandidate">PRIVATE_UNAPPROVED_DRAFT</div><details class="nr-note-history" open><summary>내부 문안 이력</summary><p>PRIVATE_HISTORY</p></details></section><section class="report-history">PRIVATE_REPORT_HISTORY</section></main><section class="nr-report-controls"><button id="reportPdfDownload">PDF 저장</button></section></body></html>'}
};
const csp="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.NAVER_REPORT_BROWSER?{executablePath:process.env.NAVER_REPORT_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1200,height:980}}),errors=[],unexpected=[];
  page.on('pageerror',error=>errors.push(error.message));
  try {
    await page.route('**/*',route=>{
      const url=new URL(route.request().url()), response=url.origin==='http://report-layout.invalid'&&routes[url.pathname];
      if(!response){unexpected.push(route.request().url());return route.abort();}
      return route.fulfill({...response,headers:{'Content-Security-Policy':csp,'Cache-Control':'no-store','X-Frame-Options':'DENY'}});
    });
    await page.goto('http://report-layout.invalid/');
    await page.evaluate(report=>{
      window.printViolations=[];document.addEventListener('securitypolicyviolation',event=>window.printViolations.push(event.violatedDirective));
      function h(tag,attrs,...children){const element=document.createElement(tag);for(const [key,value] of Object.entries(attrs||{})){if(value===false||value==null)continue;if(key.startsWith('on'))element.addEventListener(key.slice(2),value);else element.setAttribute(key,value===true?'':String(value));}
        function add(child){if(child===false||child==null)return;if(Array.isArray(child))child.forEach(add);else element.appendChild(typeof child==='object'?child:document.createTextNode(String(child)));}children.forEach(add);return element;}
      window.qaUI=NaverReports.create({h,put(){},$:id=>document.getElementById(id),num:n=>n==null?'—':String(n),won:n=>Math.trunc(n).toLocaleString('ko-KR')+'원',
        periodText:(a,b)=>a+' ~ '+b,datedTime:t=>t||'미보관',context:()=> 'fixed',active:()=>true,selection:()=> 'all',validation:()=>null,changes:()=>null,
        denied:()=>false,purge(){},go(){},toast(){},api(){throw new Error('QA has no API');},fetchList(){throw new Error('QA has no source collection');}});
      window.qaReport=report;window.qaPrints=[];window.print=()=>{const node=document.querySelector('#naver-report-print-root');window.qaPrints.push({layout:node.getAttribute('data-layout'),text:node.innerText});};
    },report);
    // Ctrl/Cmd+P does not invoke the controlled API or set nr-printing.
    await page.evaluate(()=>{const paper=qaUI.makePaper(qaReport,{layout:'a'});paper.id='directPrintPaper';document.body.appendChild(paper);});
    await page.emulateMedia({media:'print'});
    const direct=await page.evaluate(()=>({printing:document.body.classList.contains('nr-printing'),
      privateNodes:Array.from(document.querySelectorAll('.nr-internal-review,.nr-annotations,.nr-note-history,.report-history,.nr-report-controls,[id^="reportNote-"],#reportNotesCandidate')).map(node=>({selector:node.id||node.className,height:node.getBoundingClientRect().height})),
      publicHeight:document.getElementById('directPrintPaper').getBoundingClientRect().height,
      publicText:document.getElementById('directPrintPaper').textContent}));
    assert.equal(direct.printing,false);assert.ok(direct.privateNodes.length>=8);
    for(const node of direct.privateNodes)assert.equal(node.height,0,'direct browser print exposes '+node.selector);
    assert.ok(direct.publicHeight>0);assert.ok(direct.publicText.includes('합성 검증용 승인 코멘트'));assert.ok(!direct.publicText.includes('PRIVATE'));
    await page.emulateMedia({media:'screen'});await page.locator('#directPrintPaper').evaluate(node=>node.remove());
    console.log('direct browser print: PASS; public paper visible, editor/notes/history/controls hidden without nr-printing');
    for(const layout of ['a','b','c']) {
      const result=await page.evaluate(async layout=>{
        const paper=qaUI.makePaper(qaReport,{layout,print:true});
        return NaverReportPDF.print(qaReport,{layout,paper,isCurrent:()=>true});
      },layout);
      assert.deepEqual(result,{started:true});
      await page.emulateMedia({media:'print'});
      const state=await page.evaluate(()=>{
        const root=document.querySelector('#naver-report-print-root'),paper=root.querySelector('.nr-report-paper'),table=paper.querySelector('.nr-metric-table');
        return {rootCount:document.querySelectorAll('#naver-report-print-root').length,display:getComputedStyle(root).display,
          editorDisplay:getComputedStyle(document.getElementById('editor')).display,canvasColor:getComputedStyle(document.documentElement).backgroundColor,layout:paper.getAttribute('data-layout'),text:paper.textContent,
          caveatDisplay:getComputedStyle(paper.querySelector('.nr-public-caveat')).display,
          privateCount:paper.querySelectorAll('textarea,input,select,button,.nr-annotations,.nr-note-history').length,
          closedDetails:paper.querySelectorAll('details:not([open])').length,metricRows:table?.querySelectorAll('tbody tr').length,
          overflow:paper.scrollWidth>paper.clientWidth+1,violations:window.printViolations};
      });
      assert.equal(state.rootCount,1);assert.notEqual(state.display,'none');assert.equal(state.editorDisplay,'none');assert.equal(state.layout,layout);
      assert.equal(state.canvasColor,'rgb(255, 255, 255)');
      assert.equal(state.privateCount,0);assert.equal(state.closedDetails,0);assert.equal(state.metricRows,17);assert.equal(state.overflow,false);
      assert.ok(state.text.includes('합성 검증용 승인 코멘트'));assert.ok(state.text.includes('실제 주문·결제 매출'),state.text.slice(-1500));assert.notEqual(state.caveatDisplay,'none');assert.ok(!state.text.includes('PRIVATE'));
      assert.deepEqual(state.violations,[]);
      if(writePDFs){fs.mkdirSync(artifacts,{recursive:true});const target=path.join(artifacts,'naver-report-layout-'+layout+'.pdf');
        const bytes=await page.pdf({path:target,format:'A4',printBackground:true,preferCSSPageSize:true});assert.equal(bytes.subarray(0,5).toString(),'%PDF-');
        console.log('PDF QA artifact: '+target+' ('+bytes.length+' bytes)');}
      await page.evaluate(()=>window.dispatchEvent(new Event('afterprint')));
      assert.equal(await page.locator('#naver-report-print-root').count(),0);
      await page.emulateMedia({media:'screen'});
      console.log('native print '+layout.toUpperCase()+': PASS; public renderer, 17 metrics, external CSS CSP, print-only scope, cleanup'+(writePDFs?', synthetic A4 PDF':''));
    }
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    assert.equal(await page.evaluate(()=>qaPrints.length),3);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
