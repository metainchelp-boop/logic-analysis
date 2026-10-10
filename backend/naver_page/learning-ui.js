/* Versioned account evidence. All verdicts come from the server; no advertising writes. */
(function () {
  'use strict';
  var KINDS = {performance:'성과 관측',setting_change:'세팅 변경 기록',experiment:'A/B 실험'};
  var STATES = {draft:'검수 전',reviewed:'검수 완료',rejected:'반려'};
  var OUTCOMES = {observation:'관측 기록 · 인과 미입증',unknown:'판정 보류',invalid:'유효 조건 미충족',inconclusive:'차이 미확정',winner:'통계적 차이 확인'};
  var REASONS = {observed_performance:'성과 관측',planned_change:'변경 계획 · 실제 집행 아님',observed_change:'변경 관측',applied_change:'적용 기록',no_causal_control:'인과 비교 없음',running:'진행 중',stopped:'중단됨',horizon_not_complete:'계획 기간 미완료',not_preregistered:'실험 전 사전 등록 미확인',not_randomized:'무작위 배정 미확인',not_independent:'독립 관측 단위 미확인',independent_units_unknown:'독립 관측 단위 미확인',multiple_variables:'단일 변수 비교 미확인',measurement_incomplete:'집계 미완료',conversion_definition_unknown:'전환 정의 미확인',lag_not_mature:'전환 지연 미반영',allocation_invalid:'배정 유효성 미확인',sample_ratio_mismatch:'표본 비율 불일치',missing_metrics:'필요 수치 미확인',invalid_binary_counts:'비율 분자·분모 오류',goal_requires_variance:'CPA·ROAS 분산 자료 필요',insufficient_sample:'표본 부족',predeclared_sample_below_power:'사전 표본 기준 부족',no_statistical_separation:'통계적 차이 없음',below_mde:'최소 의미 차이 미달',qualified_difference:'계획 조건 내 차이 확인',protocol_changed:'사전 실험 계획 변경'};
  var ENUMS = {
    industry:{food:'식품',pet:'반려동물',home:'생활·주거',beauty:'뷰티',fashion:'패션',local_service:'지역 서비스',b2b:'B2B',other:'기타'},
    goal:{impressions:'노출수',clicks:'클릭수',cpa:'광고 전환 CPA',roas:'광고 전환가치 ROAS',ctr:'클릭률',cvr:'광고 전환율'},
    ad_type:{powerlink:'파워링크',shopping:'쇼핑',brand:'브랜드',place:'플레이스',display:'디스플레이',other:'기타'},
    budget_band:{under_300k:'월 30만원 미만', '300k_1m':'월 30만~100만원 미만','1m_3m':'월 100만~300만원 미만',over_3m:'월 300만원 이상'}
  };
  var METRICS = {impressions:'노출수',clicks:'클릭수',spend:'광고비(원)',conversions:'광고 전환수',conversion_value:'광고 전환가치(원)'};
  var SETTINGS = {goal:'운영 목표',target_value:'목표 값',daily_spend_cap:'하루 지출 상한(원)',absolute_bid_cap:'절대 입찰 상한(원)',experiment_days:'실험 기간(일)',loss_cap:'허용 손실 상한(원)',bid:'입찰가(원)',daily_budget:'일 예산(원)',enabled:'광고 활성 여부'};
  var CONVERSIONS = {unknown:'미확인',platform:'플랫폼 전체 전환',purchase:'구매 완료로 확인',lead:'문의·신청으로 확인'};
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function plain(value) { return !!value && typeof value === 'object' && !Array.isArray(value); }
  function safeNumber(value, integer) { return typeof value === 'number' && isFinite(value) && value >= 0 && value <= 1e15 && (!integer || Number.isSafeInteger(value)); }
  function localTime(value) {
    if (!value) return ''; var d = new Date(value); if (isNaN(d)) return '';
    function pad(n) { return ('0' + n).slice(-2); }
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());
  }
  function validDay(value) { return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !isNaN(new Date(value)) && new Date(value).toISOString().slice(0,10) === value; }
  function create(env) {
    var h = env.h, put = env.put, drafts = {}, shown = null, busy = false, generation = 0;
    function accountKey(account) { return account.possibility_id+'|'+account.account_key; }
    function active(ctx) { return shown === ctx && ctx.generation === generation && ctx.guard() && env.active() && ctx.context === env.context() && (!ctx.root || ctx.root.isConnected !== false); }
    function items(ctx) { return ctx.assets.items; }
    function draftFor(ctx) { return drafts[accountKey(ctx.account)]; }
    function rowFor(ctx,id) { return items(ctx).find(function (item) { return item.asset_id === id; }); }
    function stale(ctx,draft) { var row = rowFor(ctx,draft.asset_id); return (row ? row.version : 0) !== draft.baseVersion; }
    function editable(ctx,draft) { return ctx.canEdit && !busy && !stale(ctx,draft) && !Object.keys(draft.document.source_refs || {}).length; }
    function hasUnsaved() { return Object.keys(drafts).some(function (key) { return drafts[key].dirty; }); }
    if (window.addEventListener) window.addEventListener('beforeunload',function (event) { if (hasUnsaved()) { event.preventDefault(); event.returnValue = ''; } });
    function valid(draft) {
      var doc = draft.document, e = doc.evidence;
      if (!doc.title.trim() || doc.title.length > 160 || Object.keys(draft.invalid).some(function (key) { return draft.invalid[key]; })) return false;
      if (doc.kind !== 'setting_change') {
        if (!validDay(e.period_start) || !validDay(e.period_end) || e.period_start > e.period_end || (new Date(e.period_end)-new Date(e.period_start))/86400000 > 366) return false;
      }
      if (doc.kind === 'experiment' && (!(e.min_sample_per_arm > 0) || !(e.mde_percent >= 0.1 && e.mde_percent <= 100) || !(e.control_share >= 0.1 && e.control_share <= 0.9) || e.baseline_rate !== null && !(e.baseline_rate > 0 && e.baseline_rate < 1))) return false;
      if (doc.kind === 'setting_change' && e.execution !== 'planned' && !e.observed_at) return false;
      return true;
    }
    function capability(body) {
      var ctx = shown; if (!ctx || !active(ctx) || busy || !ctx.canEdit || !plain(body) || body.possibility_id !== ctx.account.possibility_id || body.account_key !== ctx.account.account_key) return false;
      if (body.action === 'capture') return Object.keys(body).sort().join('|') === 'account_key|action|possibility_id';
      if (!Number.isSafeInteger(body.expected_version) || !/^[A-Za-z0-9_-]{1,80}$/.test(body.asset_id || '')) return false;
      var draft = draftFor(ctx), row = rowFor(ctx,body.asset_id);
      if (body.action === 'save') return Object.keys(body).sort().join('|') === 'account_key|action|asset_id|document|expected_version|possibility_id' && !!draft && draft.asset_id === body.asset_id && draft.baseVersion === body.expected_version && draft.dirty && editable(ctx,draft) && valid(draft) && JSON.stringify(body.document) === JSON.stringify(draft.document);
      return (body.action === 'review' || body.action === 'reject') && Object.keys(body).sort().join('|') === 'account_key|action|asset_id|expected_version|possibility_id' && !!row && row.state === 'draft' && row.version === body.expected_version && !(draft && draft.asset_id === row.asset_id && draft.dirty);
    }
    function write(ctx,body) {
      if (!active(ctx) || !capability(body)) return;
      var mark = generation, pending = env.api('POST','/automation/learning',body); busy = true; draw(ctx);
      return pending.then(function () {
        if (!active(ctx)) return;
        busy = false;
        if (body.action === 'save') delete drafts[accountKey(ctx.account)];
        env.toast(body.action === 'capture' ? '저장 보고서를 성과 관측 자산으로 연결했습니다.' : body.action === 'review' ? '학습 자산을 검수했습니다. 서버 판정과 한계를 함께 참고합니다.' : body.action === 'reject' ? '학습 자산을 반려했습니다. 기록은 보존됩니다.' : '학습 자산 초안을 저장했습니다. 광고는 변경하지 않았습니다.');
        return ctx.onSaved();
      }).catch(function (error) {
        if (mark !== generation) return;
        busy = false;
        if (env.denied(error)) { env.purge(error); return; }
        if (!active(ctx)) return;
        ctx.message = error && error.status === 409 ? '저장 판이 변경되었습니다. 입력 초안은 보존됩니다. 최신 자료를 확인해 주세요.' : '저장 또는 최신 자료 확인을 완료하지 못했습니다. 입력과 연결 상태를 확인해 주세요.';
        draw(ctx);
      }).then(function () { if (mark === generation) busy = false; });
    }
    function start(ctx,kind,row) {
      if (!active(ctx) || busy || (!row && !ctx.canEdit)) return;
      var old = draftFor(ctx); if (old && old.dirty) { ctx.message = '저장하지 않은 초안이 있습니다. 먼저 저장하거나 입력 초안을 버려 주세요.'; draw(ctx); return; }
      if (!row && (!window.crypto || typeof window.crypto.randomUUID !== 'function')) { ctx.message = '안전한 자산 식별자를 만들 수 없습니다. 보안 연결에서 다시 열어 주세요.'; draw(ctx); return; }
      var document = copy(row ? row.document : ctx.assets.templates[kind]);
      drafts[accountKey(ctx.account)] = {asset_id:row ? row.asset_id : 'manual-'+window.crypto.randomUUID(),baseVersion:row ? row.version : 0,document:document,baseline:JSON.stringify(document),dirty:!row,invalid:{}};
      ctx.message = ''; draw(ctx);
    }
    function label(text,control) { return h('label',{class:'na-field'},h('span',null,text),control); }
    function editor(ctx,draft) {
      var doc = draft.document, evidence = doc.evidence, locked = !editable(ctx,draft), id = 'learning-'+draft.asset_id+'-';
      function change(path,value,error) {
        if (!active(ctx) || !editable(ctx,draft)) return;
        var target = doc; path.slice(0,-1).forEach(function (key) { target = target[key]; }); target[path[path.length-1]] = value;
        draft.invalid[path.join('.')] = !!error;
        draft.dirty = JSON.stringify(doc) !== draft.baseline || draft.baseVersion === 0 || Object.keys(draft.invalid).some(function (key) { return draft.invalid[key]; });
        var save = ctx.root.querySelector('[data-learning-save]'); if (save) save.disabled = !draft.dirty || !valid(draft) || !editable(ctx,draft);
        var status = ctx.root.querySelector('[data-learning-draft]'); if (status) status.textContent = draft.dirty ? '저장되지 않은 입력 초안입니다. 검수·실제 집행 전입니다.' : '저장된 자산을 보고 있습니다.';
      }
      function select(path,text,choices,nullable) {
        var value = doc; path.forEach(function (key) { value = value[key]; });
        var el = h('select',{id:id+path.join('-'),disabled:locked,onchange:function () { change(path,this.value || null); }},nullable ? h('option',{value:''},'미확인 · 미분류') : null,Object.keys(choices).map(function (key) { return h('option',{value:key},choices[key]); })); el.value = value == null ? '' : value; return label(text,el);
      }
      function input(path,text,kind,integer) {
        var value = doc; path.forEach(function (key) { value = value[key]; });
        var el = h('input',{id:id+path.join('-'),type:kind || 'number',step:integer ? 1 : 'any',min:kind ? null : 0,max:kind ? null : 1e15,maxlength:kind === 'text' ? 160 : null,disabled:locked,oninput:function () {
          var parsed = this.value === '' ? null : this.value, invalid = false;
          if (!kind) { parsed = this.value === '' ? null : Number(this.value); invalid = !!(this.validity && this.validity.badInput) || parsed !== null && !safeNumber(parsed,integer); }
          if (kind === 'datetime-local' && parsed) { var date = new Date(parsed); invalid = isNaN(date); parsed = invalid ? null : date.toISOString(); }
          change(path,kind === 'text' && parsed === null ? '' : parsed,invalid);
        }}); el.value = kind === 'datetime-local' ? localTime(value) : value == null ? '' : value; return label(text,el);
      }
      function check(path,text) {
        var value = doc; path.forEach(function (key) { value = value[key]; });
        var el = h('input',{type:'checkbox',disabled:locked,onchange:function () { change(path,this.checked); }}); el.checked = value === true;
        return h('label',null,el,' ',text);
      }
      function metrics(prefix) { return h('div',{class:'na-field-grid'},Object.keys(METRICS).map(function (key) { return input(prefix.concat(key),METRICS[key],null,['impressions','clicks','conversions'].indexOf(key) !== -1); })); }
      var fields = [input(['title'],'기록 이름','text'),h('div',{class:'na-field-grid'},Object.keys(ENUMS).map(function (key) { return select(['metadata',key],{industry:'업종',goal:'운영 목표',ad_type:'광고 유형',budget_band:'월 예산 구간'}[key],ENUMS[key],true); }))];
      if (doc.kind !== 'setting_change') fields.push(h('div',{class:'na-field-grid'},input(['evidence','period_start'],'관측 시작일','date'),input(['evidence','period_end'],'관측 종료일','date')));
      if (doc.kind === 'performance') fields.push(metrics(['evidence']));
      if (doc.kind === 'experiment') {
        fields.push(h('p',{class:'hint'},'실험 시작 전에 계획을 등록합니다. 과거 결과를 사후 입력하면 사전 등록된 실험으로 인정되지 않습니다. 실험 표본과 지출은 실제 관측값을 입력하세요.'),
          h('div',{class:'na-field-grid'},select(['evidence','status'],'실험 상태',{running:'진행 중',completed:'종료',stopped:'중단'}),select(['evidence','goal'],'1차 판정 지표',{ctr:'클릭률',cvr:'광고 전환율',cpa:'광고 전환 CPA',roas:'광고 전환가치 ROAS'}),
            input(['evidence','min_sample_per_arm'],'사전 최소 표본 수 · 각 군',null,true),input(['evidence','baseline_rate'],'사전 기준 비율(0~1)'),input(['evidence','mde_percent'],'최소 의미 차이(상대 %)'),input(['evidence','control_share'],'계획 대조군 비중(0.1~0.9)'),input(['evidence','preregistered_at'],'사전 계획 시각 · 브라우저 현지 시각','datetime-local')),
          h('fieldset',null,h('legend',null,'대조군 A · 실제 성과'),metrics(['evidence','control'])),h('fieldset',null,h('legend',null,'실험군 B · 실제 성과'),metrics(['evidence','treatment'])),
          h('div',{class:'na-actions'},check(['evidence','randomized'],'무작위 배정을 확인함'),check(['evidence','independent_units'],'독립 관측 단위 확인'),check(['evidence','one_variable'],'한 가지 변수만 비교함'),check(['evidence','allocation_valid'],'계획에 따른 배정과 집행을 확인함')));
      }
      if (doc.kind !== 'setting_change') fields.push(h('div',{class:'na-field-grid'},select(['evidence','conversion_definition'],'전환의 실제 의미',CONVERSIONS)),h('div',{class:'na-actions'},check(['evidence','measurement_complete'],'필요 기간의 집계 완결 확인'),check(['evidence','lag_mature'],'전환 지연 반영 완료 확인')));
      if (doc.kind === 'setting_change') {
        fields.push(h('p',{class:'hint'},'변경 제안과 실제 적용을 구분합니다. 실제 설정을 관측한 시각과 변경 전후 값을 기록하세요. 계획 저장 이력은 실제 네이버 광고 적용의 증거가 아닙니다.'),
          h('div',{class:'na-field-grid'},select(['evidence','execution'],'기록 종류',{planned:'변경 계획',observed:'설정 관측',applied:'적용 기록'}),select(['evidence','changed_variable'],'주요 변경 변수',Object.assign({multiple:'여러 변수 · 단일 변수 비교 아님'},SETTINGS)),input(['evidence','observed_at'],'관측 시각 · 브라우저 현지 시각','datetime-local')));
        Object.keys(SETTINGS).forEach(function (key) {
          var selected = Object.prototype.hasOwnProperty.call(evidence.before,key) || Object.prototype.hasOwnProperty.call(evidence.after,key);
          var toggle = h('input',{type:'checkbox',disabled:locked,onchange:function () {
            if (!active(ctx) || !editable(ctx,draft)) return;
            if (this.checked) { evidence.before[key] = null; evidence.after[key] = null; } else { delete evidence.before[key]; delete evidence.after[key]; }
            draft.dirty = JSON.stringify(doc) !== draft.baseline || draft.baseVersion === 0; draw(ctx);
          }}); toggle.checked = selected;
          var values = selected ? h('div',{class:'na-field-grid'},['before','after'].map(function (side) {
            if (key === 'goal') return select(['evidence',side,key],side === 'before' ? '변경 전' : '변경 후',ENUMS.goal,true);
            if (key === 'enabled') {
              var el = h('select',{disabled:locked,onchange:function () { change(['evidence',side,key],this.value === '' ? null : this.value === 'true'); }},h('option',{value:''},'미확인'),h('option',{value:'true'},'활성'),h('option',{value:'false'},'중지')); el.value = evidence[side][key] == null ? '' : String(evidence[side][key]); return label(side === 'before' ? '변경 전' : '변경 후',el);
            }
            return input(['evidence',side,key],side === 'before' ? '변경 전' : '변경 후',null,key === 'experiment_days');
          })) : null;
          fields.push(h('fieldset',null,h('legend',null,h('label',null,toggle,' ',SETTINGS[key])),values));
        });
      }
      var readonly = Object.keys(doc.source_refs || {}).length > 0;
      return h('article',{class:'na-section'},h('h3',null,KINDS[doc.kind]+' · '+(draft.baseVersion ? env.num(draft.baseVersion)+'판' : '새 자산')),
        stale(ctx,draft) ? h('p',{class:'na-note warn'},'서버에 새 판이 있습니다. 입력 초안을 보존했으며 이 판으로는 저장할 수 없습니다.') : null,
        readonly ? h('p',{class:'na-note'},'보고서·계획에서 연결한 원천 기록입니다. 원본 수치를 수정하지 않고 검수 또는 반려할 수 있습니다.') : null,
        fields,h('p',{class:'hint'},'빈 수치는 미확인으로 저장됩니다. 실제 0건·0원인 경우 0을 입력하세요. 구매 완료가 확인되지 않은 전환을 구매로 표시하지 마세요.'),
        h('p',{'data-learning-draft':'',class:'na-note','aria-live':'polite'},draft.dirty ? '저장하지 않은 입력 초안입니다. 검수·실제 집행 전입니다.' : '저장된 자산을 보고 있습니다.'),
        h('div',{class:'na-actions'},h('button',{type:'button',class:'btn primary','data-learning-save':'',disabled:!editable(ctx,draft) || !draft.dirty || !valid(draft),onclick:function () {
          write(ctx,{possibility_id:ctx.account.possibility_id,account_key:ctx.account.account_key,action:'save',asset_id:draft.asset_id,expected_version:draft.baseVersion,document:copy(doc)});
        }},'자산 초안 저장'),h('button',{type:'button',class:'btn',disabled:busy,onclick:function () { if (!active(ctx) || busy) return; delete drafts[accountKey(ctx.account)]; ctx.message = ''; draw(ctx); }},'입력 초안 닫기·버리기')));
    }
    function draw(ctx) {
      if (shown !== ctx) return;
      var draft = draftFor(ctx), counts = ctx.assets.counts || {}, retrieval = ctx.assets.retrieval || {};
      put(ctx.root,h('h3',null,'광고 성과·실험 자산'),h('p',{class:'hint'},ctx.assets.provenance_notice || '관측과 담당자 검수 기록을 구분합니다. 검수만으로 인과관계가 입증되지는 않습니다.'),
        h('div',{class:'na-actions'},Object.keys(STATES).map(function (state) { return h('span',{class:'pill p-gray'},STATES[state]+' '+env.num(counts[state])); })),
        h('p',{class:'hint'},'표시 중 '+env.num(items(ctx).length)+'건(최대 100건) 기준 집계 · 같은 계정의 검수 사례 최대 '+env.num((retrieval.cases || []).length)+'건을 전략에서 참고합니다.'),
        ctx.message ? h('p',{class:'na-note warn','aria-live':'polite'},ctx.message) : null,
        !ctx.canEdit ? h('p',{class:'na-note'},'현재 권한·계약 단계에서는 기록을 읽을 수 있습니다. 자산 저장·검수는 허용되지 않습니다.') : null,
        h('div',{class:'na-actions'},Object.keys(KINDS).map(function (kind) { return h('button',{type:'button',class:'btn',disabled:busy || !ctx.canEdit,onclick:function () { start(ctx,kind); }},KINDS[kind]+' 등록'); }),
          h('button',{type:'button',class:'btn',disabled:busy || !ctx.canEdit,onclick:function () { write(ctx,{possibility_id:ctx.account.possibility_id,account_key:ctx.account.account_key,action:'capture'}); }},'최신 저장 보고서 편입'),
          h('button',{type:'button',class:'btn',disabled:busy,onclick:function () { if (active(ctx) && !busy) ctx.onSaved(); }},'최신 자료 확인')),
        draft ? editor(ctx,draft) : null,
        items(ctx).length ? h('div',{class:'table-wrap'},h('table',{class:'na-checklist'},h('thead',null,h('tr',null,h('th',null,'기록'),h('th',null,'상태·판정'),h('th',null,'검수와 이력'))),h('tbody',null,items(ctx).map(function (item) {
          var assessment = item.assessment || {}, refs = item.document.source_refs || {}, dirty = draft && draft.asset_id === item.asset_id && draft.dirty;
          return h('tr',null,h('td',null,h('strong',null,item.document.title || '이름 없는 기록'),h('p',{class:'hint'},KINDS[item.document.kind]+' · '+env.num(item.version)+'판'),h('p',{class:'hint'},refs.report_id ? '보고서 '+env.num(refs.report_id)+' 원천' : refs.plan_version ? '운영 계획 '+env.num(refs.plan_version)+'판 원천' : '담당자 수동 기록')),
            h('td',null,h('p',null,STATES[item.state] || '상태 미확인'),h('p',null,OUTCOMES[assessment.outcome] || '판정 미확인'),assessment.winner ? h('p',{class:'hint'},'우수군: '+(assessment.winner === 'control' ? '대조군 A' : '실험군 B')) : null,
              h('ul',{class:'hint'},(assessment.reason_codes || []).map(function (reason) { return h('li',null,REASONS[reason] || '추가 조건 확인 필요'); }))),
            h('td',null,h('p',{class:'hint'},'기록 '+env.datedTime((item.author || {}).at)),item.reviewed_at ? h('p',{class:'hint'},'검수 '+env.datedTime(item.reviewed_at)) : null,
              h('div',{class:'na-actions'},h('button',{type:'button',class:'btn sm',disabled:busy,onclick:function () { start(ctx,item.document.kind,item); }},'상세 보기'),
                ['review','reject'].map(function (action) { return h('button',{type:'button',class:'btn sm',disabled:busy || !ctx.canEdit || item.state !== 'draft' || dirty,onclick:function () { write(ctx,{possibility_id:ctx.account.possibility_id,account_key:ctx.account.account_key,action:action,asset_id:item.asset_id,expected_version:item.version}); }},action === 'review' ? '검수 완료' : '반려'); }))));
        })))) : h('p',{class:'na-note'},'저장된 학습 자산이 없습니다. 기존 보고서를 편입하거나 성과·세팅·실험 기록을 등록해 주세요.'));
    }
    function render(assets,account,canEdit,guard,onSaved) {
      if (!assets || assets.version !== 1 || !Array.isArray(assets.items) || !plain(assets.templates) || !account || typeof guard !== 'function' || typeof onSaved !== 'function') return h('p',{class:'na-note'},'학습 자산 자료를 확인하지 못했습니다.');
      var ctx = {assets:assets,account:account,canEdit:canEdit === true,guard:guard,onSaved:onSaved,context:env.context(),generation:generation,message:'',root:h('section',{class:'na-section'})}; shown = ctx; draw(ctx); return ctx.root;
    }
    function reset() { generation++; drafts = {}; shown = null; busy = false; }
    return {render:render,capability:capability,hasUnsaved:hasUnsaved,reset:reset};
  }
  window.NaverLearningAssets = {create:create};
})();
