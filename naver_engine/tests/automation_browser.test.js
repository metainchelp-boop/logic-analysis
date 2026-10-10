'use strict';
// Actual DOM/CSS and controller, synthetic in-memory endpoints only.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{chromium}=require('playwright');
const fixtureSource=fs.readFileSync('naver_engine/tests/automation_ui_model_test.js','utf8');
const fixtures=vm.runInNewContext(fixtureSource.slice(fixtureSource.indexOf('const account ='),fixtureSource.indexOf('function harness()'))+'\n({account,detail})');
const data=fixtures.detail(fixtures.account(),1,'draft');
data.accounts[0].company_name='합성 업체 <img src=x onerror=alert(1)>';
const setupLabels=['광고 구조 수집','광고 심사 상태','광고 운영 상태','광고 노출 제한','캠페인 예산 설정','캠페인 노출 기간','요일·시간 설정','지역 설정','연령 설정','제외 검색어','소재 문구·자산','운영계획 목표 기록','운영계획 예산 기록','전체 설정 완결성'];
data.setup_checks.items=setupLabels.map((label,index)=>({key:'synthetic_'+index,label,state:'unknown',summary:'저장된 자료 미확인',next_action:'자료 연결 후 확인'}));
data.setup_checks.counts={attention:0,unknown:14,verified:0,not_applicable:0};
data.policy={single_increase_percent:10,single_decrease_percent:15,rolling_day_increase_percent:30,rolling_day_decrease_percent:40,weekly_increase_requires_approval_percent:50};
const css=fs.readFileSync('backend/naver_page/app.css','utf8'),script=fs.readFileSync('backend/naver_page/automation-ui.js','utf8');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.NAVER_REPORT_BROWSER?{executablePath:process.env.NAVER_REPORT_BROWSER}:{})});
  try{
    for(const width of [320,1920]){
      const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],dialogs=[];
      page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>{dialogs.push(d.message());d.dismiss();});
      await page.route('**/*',route=>route.abort());
      await page.setContent('<main><section class="screen on"><button id="automationReload">계획 새로고침</button><div id="automationRoot"></div></section></main>');
      await page.addStyleTag({content:css});await page.addScriptTag({content:script});
      await page.evaluate(async data=>{
        const h=(tag,attrs,...children)=>{const el=document.createElement(tag);for(const[k,v]of Object.entries(attrs||{})){if(v==null||v===false)continue;if(k.startsWith('on'))el.addEventListener(k.slice(2),v);else el.setAttribute(k,v===true?'':String(v));}
          const add=value=>{if(value==null||value===false)return;if(Array.isArray(value))value.forEach(add);else el.appendChild(typeof value==='object'?value:document.createTextNode(String(value)));};children.forEach(add);return el;};
        const put=(el,...children)=>{el.replaceChildren();const holder=h('div',null,...children);while(holder.firstChild)el.appendChild(holder.firstChild);};
        window.automationCalls=[];window.serverPlan=structuredClone(data);window.automationMessages=[];
        window.ui=window.NaverAutomation.create({h,put,$:id=>document.getElementById(id),num:n=>n==null?'—':String(n),datedTime:t=>t||'시각 미확인',selection:()=> 'mine',context:()=> 'fixed',active:()=>true,denied:e=>e.status===403,purge(){throw new Error('unexpected purge');},toast:t=>window.automationMessages.push(t),
          api:async(method,path,body)=>{window.automationCalls.push({method,path,body});if(method==='POST'){
            if(path!=='/automation/plans'||body.expected_version!==window.serverPlan.plan.version)throw new Error('unexpected write');
            window.serverPlan.plan.version++;window.serverPlan.plan.state=body.action==='approve'?'approved':'draft';if(body.plan)window.serverPlan.plan.plan=body.plan;return {};
          }if(path.includes('possibility_id='))return structuredClone(window.serverPlan);return {accounts:structuredClone(data.accounts),page:0,next_page:null,execution_enabled:false};}});
        await window.ui.load();
      },JSON.parse(JSON.stringify(data)));
      await page.locator('#automationAccount').selectOption('1|'+fixtures.account().account_key);await page.waitForSelector('#automationPlan-notes');
      assert.equal(await page.locator('img,iframe,[onerror]').count(),0);assert.equal(await page.locator('#automationPlanApprove').isEnabled(),true);
      assert.equal(await page.locator('#automationPlan-target_value').inputValue(),'100');
      assert.ok((await page.locator('.na-checklist').innerText()).includes('자료 미확인'));
      assert.equal(await page.locator('.na-checklist tbody tr').count(),14);
      await page.locator('#automationPlan-notes').fill('저장 전 운영 방향');const requests=await page.evaluate(()=>automationCalls.length);
      for(const name of ['캠페인 설계','A/B 실험','데이터 학습 자산','변경 기록','AI 자동화 설정']){
        await page.getByRole('button',{name,exact:true}).click();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,width+' '+name+' overflow');
        assert.equal(await page.evaluate(()=>automationCalls.length),requests,'local tab switch must not load or generate');
      }
      assert.equal(await page.locator('#automationPlan-notes').inputValue(),'저장 전 운영 방향');assert.equal(await page.locator('#automationPlanApprove').isDisabled(),true);
      await page.locator('#automationPlanSave').click();await page.waitForFunction(()=>document.getElementById('automationPlanApprove')?.disabled===false);
      assert.equal(await page.evaluate(()=>automationCalls.filter(c=>c.method==='POST').length),1);await page.locator('#automationPlanApprove').click();
      await page.waitForFunction(()=>document.getElementById('automationPlanStatus')?.textContent.includes('계획 승인'));
      assert.ok((await page.locator('#automationRoot').innerText()).includes('실제 광고 자동 실행은 미연결'));
      assert.equal(await page.evaluate(()=>automationCalls.filter(c=>c.method==='POST').length),2);
      assert.ok(await page.evaluate(()=>automationCalls.every(c=>c.method==='GET'||c.path==='/automation/plans')));
      assert.deepEqual(errors,[]);assert.deepEqual(dialogs,[]);console.log('automation browser: '+width+'px PASS; scoped plan save/approve, five local tabs, dirty preservation, unknown setup, execution disabled, XSS');
      await page.close();
    }
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
