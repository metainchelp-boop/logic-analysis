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
report.collection_status='conversion_unconfirmed';
report.refresh={scope:'current',status:'failed',source_collected_at:'2026-10-05T11:00:00+09:00',last_success_at:null,last_attempt_at:'2026-10-05T12:00:00+09:00'};
const list = fixtureBox.listData();
list.rows[0].status='partial';list.rows[0].collection_status=report.collection_status;list.rows[0].refresh=report.refresh;
list.rows[0].generated_at='2026-10-05T10:00:00+09:00';
report.company_name = '합성 검증 업체 <img src=x onerror=alert(1)>';
report.annotations.state='approved'; report.annotations.author={actor:0,at:'2026-09-28T10:00:00+09:00'};
report.annotations.approved_by=0; report.annotations.approved_at='2026-09-28T11:00:00+09:00';
report.annotations.history.items=[{version:1,state:'approved',author:report.annotations.author,approved_by:0,approved_at:report.annotations.approved_at,document:{internal_note:'HISTORY_PRIVATE',client_feedback:'QUESTION_PRIVATE',shared_comment:'과거 공유 코멘트'}}];
report.annotations.shared={version:1,state:'approved',metadata:report.annotations.metadata,shared_comment:'승인 문안 <svg onload=alert(2)>',next_plan:'검토 후 진행할 계획',plan_due:null,targets:{},approved_at:report.annotations.approved_at};
report.payload.details.daily=[1,2,3].map(n=>({day:'2026-09-'+(20+n),totals:{spend:100,clicks:20,impressions:500,conversions:10,conversion_value:500},ratios:{roas:500,cpa:10},coverage:{basic_complete:true,conversion_complete:n!==2}}));
const css = fs.readFileSync('backend/naver_page/app.css','utf8'), script = fs.readFileSync('backend/naver_page/report-ui.js','utf8');
const layouts = ['a','b','c'];
const draftComment = '미저장 공유 초안 <img src=x onerror=alert(3)>';

async function assertStructure(paper,layout) {
  assert.equal(await paper.getAttribute('data-layout'),layout);
  assert.equal(await paper.getAttribute('data-report-id'),String(report.report_id));
  assert.equal(await paper.getAttribute('data-revision-fingerprint'),report.revision_fingerprint);
  assert.equal(await paper.getAttribute('data-account-key'),report.scope.account_key);
  assert.ok(await paper.evaluate((node,layout)=>node.classList.contains('nr-layout-'+layout),layout));
  assert.equal(await paper.locator('.nr-metric-table tbody tr').count(),17);
  assert.equal(await paper.locator('.nr-quality-card').count(),3);
  const before = async (first,second) => assert.equal(await paper.evaluate((root,{first,second})=>{
    const a=root.querySelector(first),b=root.querySelector(second);
    return !!a && !!b && !!(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING);
  },{first,second}),true,layout+': '+first+' before '+second);
  if(layout==='a') {
    assert.equal(await paper.locator('.nr-a-review-grid .nr-chart-panel').count(),1);
    assert.equal(await paper.locator('.nr-a-review-grid .nr-shared-content').count(),1);
    await before('.nr-kpis','.nr-a-review-grid');
    await before('.nr-a-review-grid','.nr-comparison');
    assert.equal(await paper.locator('details .nr-metric-table').count(),1);
  } else if(layout==='b') {
    assert.equal(await paper.locator('.nr-analysis-grid .nr-analysis-meta .nr-quality-card').count(),3);
    assert.equal(await paper.locator('.nr-analysis-grid .nr-analysis-main .nr-comparison').count(),1);
    await before('.nr-analysis-main .nr-comparison','.nr-analysis-main .nr-chart-panel');
    await before('.nr-analysis-main .nr-chart-panel','.nr-analysis-main .nr-feedback');
    assert.equal(await paper.locator('details .nr-metric-table').count(),0);
  } else {
    assert.equal(await paper.locator('.nr-strategy-grid .nr-brief').count(),1);
    assert.equal(await paper.locator('.nr-strategy-grid .nr-feedback').count(),1);
    assert.equal(await paper.locator('.nr-strategy-plan .nr-shared-content').count(),1);
    assert.equal(await paper.locator('.nr-strategy-plan .nr-targets').count(),1);
    await before('.nr-kpis','.nr-strategy-grid');
    await before('.nr-strategy-grid','.nr-chart-panel');
    await before('.nr-chart-panel','.nr-comparison');
    assert.equal(await paper.locator('details .nr-metric-table').count(),1);
  }
}
async function frozenValues(paper) {
  return paper.evaluate(root=>({
    metrics:Array.from(root.querySelectorAll('.nr-metric-table tbody tr')).map(row=>[row.dataset.metric,row.querySelector('td').textContent]),
    quality:Array.from(root.querySelectorAll('.nr-quality-card')).map(card=>card.textContent)
  }));
}
async function assertTextSafe(page,scope) {
  assert.equal(await scope.locator('img,script[src],[onload],[onerror]').count(),0,'plain text XSS');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'page overflow');
}

(async () => {
  const browser = await chromium.launch({headless:true,...(process.env.NAVER_REPORT_BROWSER ? {executablePath:process.env.NAVER_REPORT_BROWSER} : {})});
  try {
    for (const width of [320,1920]) {
      const page = await browser.newPage({viewport:{width,height:1000}}), errors=[], dialogs=[];
      page.on('pageerror', error=>errors.push(error.message));
      page.on('dialog',dialog=>{dialogs.push(dialog.message());dialog.dismiss();});
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
        window.reportRequests=[]; window.frozenReport=structuredClone(report);
        window.frozenReportJSON=JSON.stringify(window.frozenReport);
        window.testReportUI=window.NaverReports.create({h,put,$:id=>document.getElementById(id),num:n=>n==null?'—':String(n),won:n=>Math.trunc(n).toLocaleString('ko-KR')+'원',periodText:(a,b)=>a+'~'+b,datedTime:t=>t||'미보관',
          context:()=> 'fixed',active:()=>true,selection:()=> 'all',onList(){},onDetailVerified(){},validation:()=>null,changes:()=>null,denied:()=>false,purge(){},go(){},toast(){},
          fetchList:(path,apply)=>{window.reportRequests.push({method:'GET',path});apply(list);return Promise.resolve();},api:(method,path)=>{window.reportRequests.push({method,path});if(method!=='GET'||!path.startsWith('/reports/detail?'))throw new Error('unexpected API');return Promise.resolve(structuredClone(report));}});
        await window.testReportUI.load(); document.querySelector('#reportsRows button').click();
      },{report:JSON.parse(JSON.stringify(report)),list:JSON.parse(JSON.stringify(list))});
      await page.waitForSelector('.nr-report-paper');
      const listText=await page.locator('#reportsRows').textContent();
      assert.ok(listText.includes('기본 자료 완결 · 전환 미확인'));
      assert.ok(listText.includes('재대조 실패 · 확인 필요'));
      assert.ok(listText.includes('성과 수집 2026-10-05T11:00:00+09:00'));
      assert.ok(listText.includes('기본·전환 전체 재대조 성공 미확인'));
      const refreshText=await page.locator('.nr-refresh-summary').textContent();
      assert.ok(refreshText.includes('재대조 실패 · 확인 필요'));
      assert.ok(refreshText.includes('전체 기간 완결을 뜻하지 않습니다'));
      assert.ok(refreshText.includes('수치판 생성 '+report.generated_at));
      const requests=await page.evaluate(()=>window.reportRequests.length);
      const baseline=await frozenValues(page.locator('.nr-report-paper'));
      await page.locator('#reportNote-shared_comment').fill(draftComment);
      await page.locator('#reportNote-internal_note').fill('DIRTY_PRIVATE');
      for(const layout of layouts) {
        await page.locator('#reportLayout-'+layout).click();
        const paper=page.locator('.nr-report-paper[data-layout="'+layout+'"]');
        assert.equal(await page.locator('.nr-report-paper').count(),1);
        await assertStructure(paper,layout);
        assert.deepEqual(await frozenValues(paper),baseline,'same frozen values in '+layout);
        assert.equal(await page.locator('#reportLayout-'+layout).getAttribute('aria-pressed'),'true');
        assert.equal(await page.locator('#reportNote-shared_comment').inputValue(),draftComment);
        assert.equal(await page.locator('#reportNote-internal_note').inputValue(),'DIRTY_PRIVATE');
        assert.equal(await page.evaluate(()=>window.testReportUI.hasUnsaved()),true);
        await assertTextSafe(page,page.locator('#reportDetail'));
        await page.locator('#reportChart').getByRole('button',{name:'ROAS',exact:true}).click();
        assert.equal(await page.locator('#reportChart .nr-dot').count(),2,'partial ROAS dates in '+layout);
        assert.equal(await page.locator('#reportChart polyline').count(),2,'partial dates break lines in '+layout);
        await page.locator('#reportSharePreview').click();
        await assertStructure(page.locator('.nr-report-paper'),layout);
        assert.deepEqual(await frozenValues(page.locator('.nr-report-paper')),baseline);
        assert.equal(await page.locator('#reportDetail textarea').count(),0);
        const shared=await page.locator('#reportDetail').textContent();
        assert.ok(shared.includes('승인 문안 <svg onload=alert(2)>'));
        assert.ok(shared.includes('합성 검증 업체 <img src=x onerror=alert(1)>'));
        assert.ok(!shared.includes('PRIVATE')); assert.ok(!shared.includes('당시 내부 메모'));
        assert.ok(!shared.includes(draftComment),'shared view must use approved notes');
        assert.equal(await page.locator('#reportDetail .nr-note-history').count(),0);
        await assertTextSafe(page,page.locator('#reportDetail'));
        assert.equal(await page.evaluate(()=>window.reportRequests.length),requests,'layout and local tabs must not request data');
        await page.locator('#reportSharePreview').click();
        assert.equal(await page.locator('#reportNote-shared_comment').inputValue(),draftComment,'draft survives shared view');
        assert.equal(await page.locator('#reportNote-internal_note').inputValue(),'DIRTY_PRIVATE');
        console.log('report enrichment browser: '+width+'px '+layout.toUpperCase()+' PASS; distinct structure, 17 metrics, 3 quality cards, dirty drafts, shared privacy, XSS, partial chart, no tab requests');
      }
      const liveHTML=await page.locator('#reportDetail').evaluate(root=>root.outerHTML);
      for(const layout of layouts) {
        const detached=await page.evaluate(layout=>{
          const paper=window.testReportUI.makePaper(window.frozenReport,{layout,print:true});
          const detached=!paper.isConnected && paper!==document.querySelector('.nr-report-paper');
          const host=document.createElement('section'); host.id='printTestRoot'; host.appendChild(paper); document.body.appendChild(host);
          return detached;
        },layout);
        assert.equal(detached,true,'print uses independent DOM');
        const paper=page.locator('#printTestRoot .nr-report-paper');
        await assertStructure(paper,layout);
        assert.deepEqual(await frozenValues(paper),baseline);
        assert.equal(await paper.locator('#reportChart,button,input,select,textarea,[role="button"],.nr-note-history,.report-history,.nr-annotations').count(),0,'print excludes interactive and private UI');
        assert.equal(await paper.locator('details:not([open])').count(),0,'print details are expanded');
        const text=await paper.textContent();
        assert.ok(text.includes('승인 문안 <svg onload=alert(2)>'));
        assert.ok(!text.includes('PRIVATE')); assert.ok(!text.includes(draftComment));
        await assertTextSafe(page,paper);
        assert.equal(await page.locator('#reportDetail').evaluate(root=>root.outerHTML),liveHTML,'print leaves live report unchanged');
        assert.equal(await page.locator('#reportNote-shared_comment').inputValue(),draftComment);
        assert.equal(await page.evaluate(()=>JSON.stringify(window.frozenReport)===window.frozenReportJSON),true,'renderer preserves frozen source');
        assert.equal(await page.evaluate(()=>window.reportRequests.length),requests,'print renderer does not request data');
        await page.locator('#printTestRoot').evaluate(root=>root.remove());
        console.log('report enrichment browser: '+width+'px '+layout.toUpperCase()+' print PASS; independent DOM, frozen values, approved notes, expanded details, no private or interactive UI');
      }
      assert.deepEqual(errors,[]);
      assert.deepEqual(dialogs,[],'XSS did not execute');
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
