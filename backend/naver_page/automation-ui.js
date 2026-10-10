/* 계정별 계획 검토. 저장·승인 API만 사용하며 광고 실행 요청은 만들지 않는다. */
(function () {
  'use strict';
  var GOALS = {impressions:'노출수',clicks:'클릭수',cpa:'광고 전환 CPA',roas:'광고 전환가치 ROAS'};
  var TABS = {design:'캠페인 설계',experiments:'A/B 실험',improve:'데이터 학습 자산',settings:'AI 자동화 설정',history:'변경 기록'};
  var NUMBERS = ['target_value','daily_spend_cap','absolute_bid_cap','experiment_days','loss_cap'];
  function finite(value) { return typeof value === 'number' && isFinite(value); }
  function documentPlan(raw) {
    raw = raw || {}; var result = {goal:Object.prototype.hasOwnProperty.call(GOALS,raw.goal) ? raw.goal : null,notes:typeof raw.notes === 'string' ? raw.notes : ''};
    NUMBERS.forEach(function (key) { result[key] = finite(raw[key]) ? raw[key] : null; });
    return result;
  }
  function complete(plan) {
    return Object.prototype.hasOwnProperty.call(GOALS,plan.goal) && NUMBERS.every(function (key) { return finite(plan[key]) && plan[key] > 0 && plan[key] <= 1e12; }) &&
      Number.isInteger(plan.experiment_days) && plan.experiment_days >= 2 && plan.experiment_days <= 30 && plan.loss_cap <= plan.daily_spend_cap * plan.experiment_days;
  }
  function renderSetup(env,data) {
    var h = env.h;
    if (!data || data.version !== 1 || !Array.isArray(data.items)) return h('section',{class:'na-section'},h('h3',null,'설정 완결 점검'),h('p',{class:'na-note'},'이 계정의 저장된 설정 점검 자료를 확인하지 못했습니다. 미확인은 설정 오류나 정상 판정이 아닙니다.'));
    var states = {attention:'확인 필요',unknown:'자료 미확인',verified:'관측 범위 확인',not_applicable:'해당 없음'}, source = data.source || {}, counts = data.counts || {};
    return h('section',{class:'na-section'},h('h3',null,'설정 완결 점검'),h('div',{class:'na-actions'},Object.keys(states).map(function (name) {
      return h('span',{class:'pill ' + (name === 'attention' ? 'p-amber' : name === 'verified' ? 'p-green' : 'p-gray')},states[name] + ' ' + env.num(counts[name]));
    })),h('p',{class:'hint'},'저장된 원천 설정과 계획에서 확인한 범위입니다. 자료 미확인을 설정 누락으로 보지 않으며, 일부 상태 확인이 전체 세팅 완료를 뜻하지 않습니다.'),
      h('table',{class:'na-checklist'},h('thead',null,h('tr',null,h('th',null,'점검 항목'),h('th',null,'상태'),h('th',null,'관측과 다음 작업'))),h('tbody',null,data.items.map(function (item) {
        return h('tr',null,h('th',{scope:'row'},item.label),h('td',null,states[item.state] || '자료 미확인'),
          h('td',null,h('p',null,item.summary),h('p',{class:'hint'},item.next_action)));
      }))),h('p',{class:'na-plan-meta'},'구조 원천 수집 ' + env.datedTime((source.structure || {}).checked_at) + ' · 캠페인 원천 수집 ' + env.datedTime((source.campaigns || {}).checked_at)),
      Array.isArray(source.limitations) ? h('ul',{class:'hint'},source.limitations.map(function (line) { return h('li',null,line); })) : null);
  }
  function create(env) {
    var h = env.h, put = env.put, $ = env.$, epoch = 0, shown = null, displayedMark = null, displayedContext = null;
    var selected = null, rows = [], listing = null, drafts = {}, busy = false, controller = null, tab = env.learningEntry === true ? 'improve' : 'settings', q = '', page = 0, timer = null, initialized = false;
    var learningUI = window.NaverLearningAssets ? window.NaverLearningAssets.create(env) : null;
    function key(account) { return account.possibility_id + '|' + account.account_key; }
    function fresh(mark,ctx) { return mark === epoch && ctx === env.context() && env.active(); }
    function identity(data,account) {
      var s = data && data.selection, m = data && data.plan && data.plan.metadata;
      return !!s && !!m && s.possibility_id === account.possibility_id && s.account_key === account.account_key &&
        m.possibility_id === account.possibility_id && m.account_key === account.account_key && Number.isSafeInteger(data.plan.version) && data.plan.version >= 0;
    }
    function hasUnsaved() { return Object.keys(drafts).some(function (name) { return drafts[name].dirty; }) || !!learningUI && learningUI.hasUnsaved(); }
    function learningCapability(body) { return !!learningUI && learningUI.capability(body); }
    if (window.addEventListener) window.addEventListener('beforeunload',function (event) { if (hasUnsaved()) { event.preventDefault(); event.returnValue = ''; } });
    function planCapability(body) {
      if (!body || !shown || !selected || busy || !fresh(displayedMark,displayedContext) || !identity(shown,selected)) return false;
      var head = shown.plan, draft = drafts[key(selected)];
      if (body.possibility_id !== selected.possibility_id || body.account_key !== selected.account_key ||
          !Number.isSafeInteger(body.expected_version) || body.expected_version !== head.version) return false;
      if (body.action === 'save') return shown.can_edit === true && !!body.plan && typeof body.plan === 'object' && !Array.isArray(body.plan);
      return body.action === 'approve' && body.plan === undefined && shown.can_approve === true && head.state === 'draft' &&
        !(draft && draft.dirty) && complete(documentPlan(head.plan));
    }
    function listPath() { return '/automation?selection=' + encodeURIComponent(env.selection()) + '&q=' + encodeURIComponent(q) + '&page=' + page; }
    function detailPath(account) { return '/automation?possibility_id=' + account.possibility_id + '&account_key=' + encodeURIComponent(account.account_key) + '&selection=' + encodeURIComponent(env.selection()); }
    function init() {
      if (initialized) return; initialized = true;
      if ($('automationReload')) $('automationReload').addEventListener('click',function () { if (!busy && env.active()) load(); });
    }
    function fail(error,mark,ctx) {
      if (!fresh(mark,ctx)) return;
      if (env.denied(error)) { env.purge(error); return; }
      busy = false; shown = null;
      put($('automationRoot'),h('div',{class:'card empty'},'계정별 계획을 확인하지 못했습니다. 다시 확인해 주세요. ',h('button',{type:'button',class:'btn',onclick:load},'다시 확인')));
    }
    function load() {
      if (!env.active() || busy && fresh(displayedMark,displayedContext)) return Promise.resolve(); busy = false; init();
      if (controller) controller.abort(); controller = new AbortController();
      var mark = ++epoch, ctx = env.context(); shown = null;
      put($('automationRoot'),h('div',{class:'card empty'},'현재 담당 범위의 광고 계정을 확인 중입니다…'));
      return env.api('GET',listPath(),undefined,controller.signal).then(function (data) {
        if (!fresh(mark,ctx)) return;
        if (!data || !Array.isArray(data.accounts) || data.execution_enabled !== false) throw new Error('automation-data');
        listing = data; rows = data.accounts.slice(0,100); displayedMark = mark; displayedContext = ctx;
        var account = selected && rows.find(function (item) { return key(item) === key(selected); }); selected = null;
        if (account) return open(account); render();
      }).catch(function (error) { fail(error,mark,ctx); });
    }
    function open(account) {
      if (!env.active() || busy || !Number.isSafeInteger(account.possibility_id) || account.possibility_id <= 0 || typeof account.account_key !== 'string' || !account.account_key ||
          !rows.some(function (item) { return key(item) === key(account); })) return Promise.resolve();
      if (controller) controller.abort(); controller = new AbortController();
      var mark = ++epoch, ctx = env.context(); selected = account; shown = null; displayedMark = mark; displayedContext = ctx; render();
      return env.api('GET',detailPath(account),undefined,controller.signal).then(function (data) {
        if (!fresh(mark,ctx)) return;
        if (!identity(data,account) || data.execution_enabled !== false || data.plan.execution_status !== 'not_enabled') throw new Error('automation-data');
        shown = data; render();
      }).catch(function (error) { fail(error,mark,ctx); });
    }
    function renderPicker() {
      var search = h('input',{id:'automationSearch',type:'search',maxlength:120,'aria-label':'자동화 계획 광고주·계정 검색',placeholder:'광고주·계정 검색',disabled:busy,oninput:function () {
        q = this.value.trim(); page = 0; clearTimeout(timer); timer = setTimeout(load,250);
      }}); search.value = q;
      var select = h('select',{id:'automationAccount','aria-label':'계획 작성 광고 계정',disabled:busy,onchange:function () {
        var account = rows.find(function (item) { return key(item) === this.value; },this); if (account) open(account);
      }},h('option',{value:''},'광고 계정을 선택해 주세요'),rows.map(function (item) {
        return h('option',{value:key(item)},item.company_name + ' · ' + (item.account_name || '계정') + ' · ' + (item.ad_account_no || '번호 미확인'));
      })); select.value = selected ? key(selected) : '';
      return h('div',{class:'card na-section'},h('div',{class:'na-field-grid'},h('label',{class:'na-field'},h('span',null,'담당 범위에서 찾기'),search),h('label',{class:'na-field'},h('span',null,'개별 광고 계정'),select)),
        h('div',{class:'na-actions'},h('span',{class:'hint'},'계정별 계획·승인을 따로 관리합니다. 목록은 페이지당 최대 100개입니다.'),
          page > 0 ? h('button',{type:'button',class:'btn sm',disabled:busy,onclick:function () { page--; selected = null; load(); }},'이전 계정 목록') : null,
          listing && Number.isSafeInteger(listing.next_page) ? h('button',{type:'button',class:'btn sm',disabled:busy,onclick:function () { page = listing.next_page; selected = null; load(); }},'다음 계정 목록') : null));
    }
    function status(head) { return head.state === 'approved' ? '계획 승인 · 실행 미연결' : head.state === 'draft' ? '계획 검토 전' : '계획 작성 전'; }
    function render() {
      if (!env.active()) return;
      var content = !selected ? h('div',{class:'card empty'},rows.length ? '광고 계정을 선택하면 현재 계획과 설정 점검을 확인할 수 있습니다.' : '현재 범위와 검색 조건에 맞는 광고 계정이 없습니다.') : !shown ? h('div',{class:'card empty'},'선택한 계정의 최신 계획·권한을 확인 중입니다…') : renderDetail();
      put($('automationRoot'),renderPicker(),content); if ($('automationReload')) $('automationReload').disabled = busy;
    }
    function renderDetail() {
      var data = shown, account = selected, head = data.plan, id = key(account), saved = documentPlan(head.plan), draft = drafts[id];
      if (!draft) draft = drafts[id] = {plan:documentPlan(head.plan),baseVersion:head.version,dirty:false,invalid:{}};
      if (!draft.dirty) { draft.plan = documentPlan(head.plan); draft.baseVersion = head.version; }
      var stale = draft.baseVersion !== head.version, mark = displayedMark, ctx = displayedContext;
      function current() { return fresh(mark,ctx) && shown === data && selected === account; }
      function update() {
        if (!current()) return;
        draft.dirty = Object.keys(draft.invalid).some(function (name) { return draft.invalid[name]; }) || JSON.stringify(draft.plan) !== JSON.stringify(saved);
        var invalid = Object.keys(draft.invalid).some(function (name) { return draft.invalid[name]; });
        if (!$('automationPlanSave')) return;
        $('automationPlanSave').disabled = busy || data.can_edit !== true || stale || !draft.dirty || invalid;
        $('automationPlanApprove').disabled = busy || data.can_approve !== true || stale || draft.dirty || head.state !== 'draft' || !complete(saved);
        $('automationPlanStatus').textContent = stale ? '다른 계획판이 저장되었습니다. 입력을 버린 뒤 최신 계획을 확인해 주세요.' : invalid ? '숫자는 유한한 양수, 실험 기간은 2~30일 정수로 입력해 주세요.' : draft.dirty ? '저장하지 않은 계획 초안입니다. 승인·실행되지 않았습니다.' : status(head);
      }
      function input(name,label,kind) {
        var element;
        if (name === 'goal') element = h('select',{id:'automationPlan-goal',disabled:busy || data.can_edit !== true || stale,onchange:function () {
          if (!current() || busy || data.can_edit !== true || stale) return; draft.plan.goal = this.value || null; update();
        }},h('option',{value:''},'목표 선택 · 미정'),Object.keys(GOALS).map(function (value) { return h('option',{value:value},GOALS[value]); }));
        else element = h(kind === 'textarea' ? 'textarea' : 'input',{id:'automationPlan-' + name,type:kind === 'textarea' ? null : 'number',min:kind === 'textarea' ? null : name === 'experiment_days' ? 2 : 0,
          max:name === 'experiment_days' ? 30 : kind === 'textarea' ? null : 1e12,step:name === 'experiment_days' ? 1 : 'any',maxlength:kind === 'textarea' ? 1000 : null,rows:kind === 'textarea' ? 5 : null,
          disabled:busy || data.can_edit !== true || stale,oninput:function () {
            if (!current() || busy || data.can_edit !== true || stale) return;
            var value = kind === 'textarea' ? this.value : this.value === '' ? null : Number(this.value);
            draft.invalid[name] = kind !== 'textarea' && (!!(this.validity && this.validity.badInput) || value !== null && (!finite(value) || value <= 0 || value > 1e12 || name === 'experiment_days' && (!Number.isInteger(value) || value < 2 || value > 30)));
            draft.plan[name] = value; update();
          }});
        element.value = draft.plan[name] == null ? '' : draft.plan[name];
        return h('label',{class:'na-field'},h('span',null,label),element);
      }
      function mutate(action) {
        if (!current() || busy || stale || action === 'save' && $('automationPlanSave').disabled || action === 'approve' && $('automationPlanApprove').disabled) return;
        var body = {possibility_id:account.possibility_id,account_key:account.account_key,expected_version:head.version,action:action};
        if (action === 'save') body.plan = documentPlan(draft.plan);
        if (!planCapability(body)) return;
        var pending = env.api('POST','/automation/plans',body); busy = true; render();
        pending.then(function () {
          if (!current()) return;
          return env.api('GET',detailPath(account)).then(function (verified) {
            if (!current()) return;
            if (!identity(verified,account) || verified.execution_enabled !== false || verified.plan.execution_status !== 'not_enabled') throw new Error('automation-data');
            busy = false; delete drafts[id]; shown = verified; render();
            env.toast(action === 'approve' ? '계획을 승인했습니다. 실제 광고 실행은 연결되지 않았습니다.' : '계획 초안을 저장했습니다. 광고는 변경하지 않았습니다.');
          });
        }).catch(function (error) {
          if (!fresh(mark,ctx)) return;
          if (env.denied(error)) { env.purge(error); return; }
          if (!current()) return;
          busy = false; render();
          var message = error.status === 409 ? '계획판이 바뀌었습니다. 입력 초안은 보존됩니다. 새로 확인해 주세요.' : '계획을 저장·승인하지 못했습니다. 입력 내용과 연결 상태를 확인해 주세요.';
          var statusNode = $('automationPlanStatus'); if (statusNode) statusNode.textContent = message; else env.toast(message,'warn');
        }).then(function () { if (!env.active()) busy = false; });
      }
      var editor = h('article',{class:'card'},h('h2',null,'광고주별 목표·실행 범위'),h('p',{class:'na-plan-meta'},'계획 ' + env.num(head.version) + '판 · ' + status(head)),
        head.approval_requires_lead === true ? h('p',{class:'na-note warn'},'일일 지출·절대 입찰·허용 손실 상한 인상은 팀장 등급의 검토가 필요합니다. 현재 승인 가능 여부는 서버 권한을 따릅니다.') : null,
        h('div',{class:'na-field-grid'},input('goal','운영 목표'),input('target_value','목표 값 · CPA는 원, ROAS는 %, 노출·클릭은 회'),
          input('daily_spend_cap','계정 하루 지출 상한(원)'),input('absolute_bid_cap','절대 입찰 상한(원)'),input('experiment_days','실험 기간(2~30일)'),input('loss_cap','실험 허용 손실 상한(원)')),
        h('div',{class:'na-section'},input('notes','운영 방향·검토 메모','textarea')),
        h('p',{class:'hint'},'CPA·ROAS는 현재 광고 플랫폼 전체 전환 지표입니다. 구매 완료 지표로 확인된 값으로 표현하지 않습니다. 모든 필수값과 손실 상한을 검토한 후 계획을 승인합니다.'),
        h('p',{class:'na-note',id:'automationPlanStatus','aria-live':'polite'},stale ? '다른 계획판과 입력 초안의 버전이 다릅니다.' : draft.dirty ? '저장하지 않은 계획 초안입니다.' : status(head)),
        h('div',{class:'na-actions'},h('button',{type:'button',class:'btn primary',id:'automationPlanSave',disabled:busy || data.can_edit !== true || stale || !draft.dirty || Object.keys(draft.invalid).some(function (name) { return draft.invalid[name]; }),onclick:function () { mutate('save'); }},'계획 초안 저장'),
          h('button',{type:'button',class:'btn',id:'automationPlanApprove',disabled:busy || data.can_approve !== true || stale || draft.dirty || head.state !== 'draft' || !complete(saved),onclick:function () { mutate('approve'); }},'검토 후 계획 승인'),
          h('button',{type:'button',class:'btn',disabled:busy,onclick:function () { if (!current() || busy) return; delete drafts[id]; render(); }},'입력 초안 버리기')));
      var empty = {design:['캠페인 설계','목표·예산·입찰 상한·실험 기간을 저장하고 구체적인 대상·변경 범위를 검토합니다. 현재는 계획 기록 단계이며 광고 변경 경로는 연결되지 않았습니다.'],
        experiments:['A/B 비교·판정','실험군·배분·소재별 성과·전환 지연을 연결한 판정 자료가 없습니다. 이전 기간 비교를 통제된 A/B 실험이나 승자 선정으로 표시하지 않습니다.'],
        improve:['유지·다음 실험','실제 변경·성숙한 전환·비교 조건이 확인된 결과만 다음 방향에 반영합니다. 지금은 자동 개선 실행과 승자 판정 자료가 미연결입니다.']};
      var content = tab === 'settings' ? editor : tab === 'history' ? h('article',{class:'card'},h('h2',null,'현재 계획과 승인 기록'),
        h('p',{class:'na-plan-meta'},'계획 ' + env.num(head.version) + '판 · ' + status(head)),head.author ? h('p',null,'작성자 ID ' + env.num(head.author.actor) + ' · ' + env.datedTime(head.author.at)) : null,
        h('p',null,'승인자 ID ' + (head.approved_by == null ? '미승인' : env.num(head.approved_by)) + ' · ' + env.datedTime(head.approved_at)),
        h('p',{class:'na-note'},'광고 실행·변경·복구 기록은 없습니다. 계획 승인이 실행 완료를 뜻하지 않습니다.')) : h('article',{class:'card'},h('h2',null,empty[tab][0]),h('p',{class:'na-note'},empty[tab][1]),
          h('button',{type:'button',class:'btn',onclick:function () { if (!current()) return; tab = 'settings'; render(); }},'목표·계획 작성 열기'));
      if (learningUI && (tab === 'improve' || tab === 'experiments' || tab === 'history')) {
        content = h('article',{class:'card'},learningUI.render(data.learning_assets,account,data.can_edit,current,function () { return open(account); }));
      }
      var policy = data.policy || {};
      function percent(name) { return finite(policy[name]) ? env.num(policy[name]) + '%' : '미확인'; }
      return h('div',{class:'na-content'},h('div',{class:'na-section'},h('h2',null,account.company_name + ' · ' + (account.account_name || '개별 계정')),
        h('p',{class:'na-plan-meta'},'광고 계정 ID ' + (account.ad_account_no || '미확인') + ' · 계약 단계 ' + (account.workflow || '미확인'))),
        h('div',{class:'na-note warn'},'계획·성과·세팅·실험 이력을 기록하고 검수합니다. 계획 승인과 학습 기록은 실제 광고 집행이 아닙니다. 실제 광고 자동 실행은 미연결 상태입니다. Claude는 키·모델·비용 상한 설정 후 보고서에서 명시적으로 생성합니다.'),
        h('nav',{class:'na-tabs','aria-label':'자동화 계획 보기'},Object.keys(TABS).map(function (name) { return h('button',{type:'button',class:'chip' + (tab === name ? ' on' : ''),'aria-pressed':String(tab === name),onclick:function () { if (!current()) return; tab = name; render(); }},TABS[name]); })),
        h('div',{class:'na-layout'},h('div',null,content),h('aside',{class:'card'},h('h3',null,'실행 전 준비 상태'),h('p',{class:'na-note'},'목표·한도·대상 계획을 검토하는 단계입니다. 승인 후에도 현재 실행 기능은 활성화되지 않습니다.'),
          h('p',{class:'hint'},'향후 실행 전에는 계약 단계·현재 설정·네이버 자체 자동입찰 여부를 확인해야 합니다. 현재 실제 실행 검증 경로는 미연결입니다.'),
          h('p',{class:'na-plan-meta'},'향후 실행 상한 미리보기: 1회 인상 +' + percent('single_increase_percent') + ' / 인하 −' + percent('single_decrease_percent') +
            ' · 최근 24시간 인상 +' + percent('rolling_day_increase_percent') + ' / 인하 −' + percent('rolling_day_decrease_percent') +
            ' · 7일 누적 인상 +' + percent('weekly_increase_requires_approval_percent') + ' 초과는 별도 승인'),
          h('button',{type:'button',class:'btn',disabled:true},'자동 실행 · 미연결'))),renderSetup(env,data.setup_checks));
    }
    function suspend() { epoch++; if (controller) controller.abort(); clearTimeout(timer); busy = false; shown = null; displayedMark = null; displayedContext = null; if ($('automationRoot')) put($('automationRoot')); }
    function reset() { epoch++; if (controller) controller.abort(); clearTimeout(timer); busy = false; shown = null; selected = null; rows = []; listing = null; drafts = {}; if (learningUI) learningUI.reset(); displayedMark = null; displayedContext = null; q = ''; page = 0; tab = env.learningEntry === true ? 'improve' : 'settings'; if ($('automationRoot')) put($('automationRoot')); }
    return {load:load,reset:reset,suspend:suspend,planCapability:planCapability,learningCapability:learningCapability,hasUnsaved:hasUnsaved};
  }
  window.NaverAutomation = {create:create,renderSetup:renderSetup,model:{documentPlan:documentPlan,complete:complete}};
}());
