/* 저장된 같은 판만 표시하는 계정별 보고서. API/권한/캐시는 기존 관제 입구가 제공한다. */
(function () {
  'use strict';
  var LABEL = {spend:'광고비',conversion_value:'전환 매출',roas:'ROAS',cpa:'전환당 비용',impressions:'노출',clicks:'클릭',ctr:'클릭률',cpc:'클릭당 비용',conversions:'전환',cvr:'전환율'};
  var STATUS = {ready:'생성 완료',partial:'부분 집계',collecting:'수집 중',not_generated:'아직 생성되지 않음'};
  function finite(value) { return typeof value === 'number' && isFinite(value); }
  function round(value) { return Number(value.toFixed(2)).toLocaleString('ko-KR'); }
  function metric(payload, key) {
    var values = ['ctr','cpc','roas','cvr','cpa'].indexOf(key) >= 0 ? payload.ratios : payload.totals;
    return values && finite(values[key]) ? values[key] : null;
  }
  function query(filter, selection) {
    var anchor = filter.requestAnchor === undefined ? filter.anchor : filter.requestAnchor;
    return '/reports/accounts?selection=' + encodeURIComponent(selection) + '&kind=' + filter.kind +
      (anchor ? '&anchor=' + encodeURIComponent(anchor) : '') +
      (filter.q ? '&q=' + encodeURIComponent(filter.q) : '') + '&page=' + (filter.page || 0) +
      (filter.pid ? '&possibility_id=' + filter.pid : '');
  }
  function changeText(change, key) {
    if (!change) return '비교 자료 부족';
    if (change.status === 'scope_changed') return '비교 범위 변경';
    if (change.status === 'zero_denominator') return '증감률 산출 불가';
    if (change.status !== 'ready') return '비교 자료 부족';
    var ratio = ['ctr','cvr','roas'].indexOf(key) >= 0;
    var value = ratio ? change.absolute : change.percent;
    if (!finite(value)) return '증감률 산출 불가';
    return (value > 0 ? '+' : '') + round(value) + (ratio ? '%p' : '%');
  }
  function sameEdition(a, b) {
    return !!a && !!b && a.report_id === b.report_id && a.revision_no === b.revision_no &&
      a.revision_fingerprint === b.revision_fingerprint && JSON.stringify(a.scope) === JSON.stringify(b.scope) &&
      JSON.stringify(a.payload) === JSON.stringify(b.payload) &&
      ['company_name','owner','generated_at','period_key','status','possibility_id'].every(function (key) { return JSON.stringify(a[key]) === JSON.stringify(b[key]); });
  }
  function create(env) {
    var h = env.h, put = env.put, $ = env.$;
    var filter = {kind:'weekly',anchor:'',requestAnchor:'',q:'',page:0,pid:null}, anchors = {}, epoch = 0, searchTimer;
    var selected = null, displayed = null, initialized = false, chartMetric = 'spend', lastList = null, listReady = false, listContext = null;
    function context() { return env.context(); }
    function fresh(mark, ctx) { return mark === epoch && ctx === context() && env.active(); }
    function stateLabel(status) { return STATUS[status] || '집계 상태 미확인'; }
    function value(payload, key) {
      var n = metric(payload, key);
      if (n === null) return '—';
      if (['spend','conversion_value','cpa','cpc'].indexOf(key) >= 0) return env.won(n);
      return round(n) + (['ctr','roas','cvr'].indexOf(key) >= 0 ? '%' : '');
    }
    function statusChip(status) { return h('span',{class:'pill ' + (status === 'ready' ? 'p-green' : status === 'partial' ? 'p-amber' : 'p-gray')},stateLabel(status)); }
    function init() {
      if (initialized) return;
      initialized = true;
      var search = h('input',{id:'reportSearch',type:'search',placeholder:'업체명, 계정 이름 또는 광고 계정 ID',maxlength:120,'aria-label':'보고서 업체·계정 검색',oninput:function () {
        filter.q = this.value.trim(); filter.page = 0; selected = null; displayed = null; listReady = false; epoch++;
        put($('reportDetail')); $('reportDetail').hidden = true;
        $('reportsRows').hidden = true; $('reportsPages').hidden = true;
        clearTimeout(searchTimer); searchTimer = setTimeout(function () { load(0); },250);
      }});
      put($('reportFilters'),h('div',{class:'nr-search'},h('label',{for:'reportSearch'},'업체 · 광고 계정 찾기'),search),
        h('div',{class:'nr-period-tools'},h('div',{class:'chips','aria-label':'보고서 종류'},
          h('button',{id:'reportWeekly',type:'button',class:'chip on','aria-pressed':'true',onclick:function () { changeKind('weekly'); }},'주간'),
          h('button',{id:'reportMonthly',type:'button',class:'chip','aria-pressed':'false',onclick:function () { changeKind('monthly'); }},'월간')),
          h('div',{class:'nr-date'},h('label',{for:'reportAnchor'},'보고 기간 안 날짜'),h('input',{id:'reportAnchor',type:'date','aria-label':'보고 기간 안 날짜',onchange:function () {
            if (!this.value) return; filter.anchor = this.value; filter.requestAnchor = this.value; anchors[filter.kind] = this.value; filter.page = 0; reloadPeriod();
          }}))),
        h('button',{id:'reportCompanyClear',type:'button',class:'btn sm',hidden:true,onclick:function () { filter.pid = null; selected = null; load(0); }},'업체 지정 해제'));
    }
    function controls() {
      $('reportSearch').value = filter.q;
      $('reportAnchor').value = filter.anchor;
      ['weekly','monthly'].forEach(function (kind) {
        var button = $(kind === 'weekly' ? 'reportWeekly' : 'reportMonthly');
        button.classList.toggle('on',filter.kind === kind); button.setAttribute('aria-pressed',String(filter.kind === kind));
      });
      $('reportCompanyClear').hidden = !filter.pid;
      $('reportFilters').classList.toggle('nr-detail-filters',!!selected);
      $('reportsSource').hidden = !!selected; $('reportUnlinked').hidden = !!selected;
    }
    function changeKind(kind) {
      if (filter.kind === kind) return;
      anchors[filter.kind] = filter.anchor; filter.kind = kind; filter.anchor = anchors[kind] || ''; filter.page = 0;
      filter.requestAnchor = filter.anchor;
      reloadPeriod();
    }
    function reloadPeriod() {
      if (!selected) return load(0);
      var prior = selected, mark = ++epoch, ctx = context(); displayed = null; controls();
      put($('reportDetail'),h('div',{class:'card empty'},'선택한 계정의 보고 기간을 확인 중입니다…'));
      var target = {kind:filter.kind,anchor:filter.anchor,q:prior.ad_account_no || '',page:0,pid:prior.possibility_id};
      return env.api('GET',query(target,env.selection())).then(function (data) {
        if (!fresh(mark,ctx)) return;
        filter.anchor = data.period.start; anchors[filter.kind] = filter.anchor; controls();
        var row = (data.rows || []).find(function (r) { return r.account_key === prior.account_key; });
        if (!row) { selected = null; return load(0); }
        return open(row,prior.aggregate === true ? 'company' : row.account_key);
      },function (error) { errorDetail(error,mark,ctx); });
    }
    function load(page) {
      init();
      // 미생성 기간에는 재확인할 판이 없다. 재진입도 목록의 현재 권한·생성 여부를 먼저 확인한다.
      if (selected && selected.report_id && typeof page !== 'number') return open(selected,selected.aggregate ? 'company' : selected.account_key);
      if (typeof page === 'number') filter.page = page;
      selected = null; displayed = null; listReady = false; var mark = ++epoch, ctx = context(); controls();
      $('reportDetail').hidden = true; $('reportsRows').hidden = false; $('reportsPages').hidden = false;
      return env.fetchList(query(filter,env.selection()),function (data) {
        if (!fresh(mark,ctx)) return;
        var unchanged = lastList === data && listContext === ctx && $('reportsRows').firstChild;
        lastList = data; listReady = true; env.onList(data); filter.page = data.page;
        filter.anchor = data.period.start; anchors[filter.kind] = filter.anchor; controls();
        if (!unchanged) renderList(data);
      });
    }
    function renderList(data) {
      var ctx = context();
      listContext = ctx;
      var period = data.period || {}, schedule = data.schedule || {}, rows = data.rows || [];
      $('reportsSchedule').textContent = '주간: 월~일 → ' + (schedule.weekly || '월요일 10:00') + ' · 월간: 1일~말일 → ' + (schedule.monthly || '매월 3일 10:00') + ' (한국시간)';
      put($('reportsStatus'),h('b',null,'관리 중인 광고 계정 ' + env.num(data.total) + '개'),
        ' · ' + env.periodText(period.start,period.end) + ' · 저장된 자료만 조회합니다.');
      put($('reportUnlinked'), data.unlinked_companies ? h('div',{class:'nr-notice'},
        '광고 계정 연결을 확인할 실관리 업체 ' + env.num(data.unlinked_companies) + '곳이 있습니다. ',
        h('button',{type:'button',class:'link',onclick:function () { env.go('/naver/transfers'); }},'이관 현황에서 확인')) : null);
      var labels = ['업체 / 광고 계정','담당자 · 단계','보고 기간','상태 · 갱신','보고서'];
      put($('reportsRows'),rows.length ? h('div',{class:'nr-table card'},h('table',{class:'nr-account-table'},
        h('thead',null,h('tr',null,labels.map(function (label) { return h('th',null,label); }))),
        h('tbody',null,rows.map(function (row) {
          var cells = [h('td',null,h('strong',null,row.company_name),h('span',{class:'w'},row.account_name || '계정 이름 미확인'),
              h('span',{class:'nr-id'},'광고 계정 ID ' + (row.ad_account_no || '미확인'))),
            h('td',null,row.owner && row.owner.name || '담당 미확인',h('span',{class:'w'},row.workflow || '단계 미확인')),
            h('td',null,env.periodText(period.start,period.end)),
            h('td',null,statusChip(row.status),h('span',{class:'w'},row.generated_at ? env.datedTime(row.generated_at) : '생성 후 확인할 수 있습니다')),
            h('td',null,h('button',{type:'button',class:'btn sm',disabled:!row.report_id,'aria-label':row.company_name + ' ' + (row.ad_account_no || row.account_name || '') + ' 보고서 보기',onclick:function () { if (listReady && !selected && context() === ctx && env.active() && lastList === data) open(row,row.account_key); }},row.report_id ? '보고서 보기' : '생성 대기'))];
          cells.forEach(function (cell,index) { cell.setAttribute('data-label',labels[index]); });
          return h.apply(null,['tr',{'data-account-key':row.account_key,'data-report':row.report_id}].concat(cells));
        })))) : h('div',{class:'card empty'},filter.q ? '검색 조건에 맞는 관리 계정이 없습니다. 업체명이나 광고 계정 ID를 다시 확인해 주세요.' : '현재 담당 범위에 연결된 실관리 광고 계정이 없습니다. 이관 현황에서 계정 연결을 확인해 주세요.'));
      put($('reportsPages'),filter.page > 0 ? h('button',{type:'button',class:'btn',onclick:function () { load(filter.page-1); }},'이전') : null,
        h('span',{class:'hint'},String(filter.page+1) + '페이지'),data.next_page !== null && typeof data.next_page === 'number' ?
          h('button',{type:'button',class:'btn',onclick:function () { load(data.next_page); }},'다음') : null);
    }
    function detailPath(reportId,account) { return '/reports/detail?report_id=' + reportId + '&account_key=' + encodeURIComponent(account); }
    function open(row,account) {
      if (!env.active()) return;
      selected = Object.assign({},row,{aggregate:account === 'company'}); displayed = null;
      var mark = ++epoch, ctx = context(); controls();
      $('reportDetail').hidden = false; $('reportsRows').hidden = true; $('reportsPages').hidden = true;
      if (!row.report_id) {
        put($('reportDetail'),h('div',{class:'card empty'},'선택한 기간의 보고서가 아직 생성되지 않았습니다. 다른 기간을 선택하거나 예약 집계 후 다시 확인해 주세요. ',
          h('button',{type:'button',class:'btn',onclick:function () { selected = null; load(filter.page); }},'목록으로')));
        return Promise.resolve();
      }
      put($('reportDetail'),h('div',{class:'card empty'},'저장된 보고서 판을 확인 중입니다…'));
      return env.api('GET',detailPath(row.report_id,account)).then(function (data) {
        if (!fresh(mark,ctx)) return;
        displayed = data; renderDetail(data,mark,ctx); env.onDetailVerified(data);
      },function (error) { errorDetail(error,mark,ctx); });
    }
    function errorDetail(error,mark,ctx) {
      if (!fresh(mark,ctx)) return;
      displayed = null;
      if (env.denied(error)) { env.purge(error); return; }
      put($('reportDetail'),h('div',{class:'card empty'},'이 보고서를 열 수 없습니다. 현재 담당 범위와 저장된 판을 다시 확인해 주세요. ',
        h('button',{type:'button',class:'btn',onclick:function () { selected = null; load(filter.page); }},'목록으로')));
    }
    function metricCard(report,key) {
      var p = report.payload, coverage = p.coverage || {}, comparison = p.details && p.details.comparison || {};
      var conversion = ['conversion_value','roas','cpa','conversions','cvr'].indexOf(key) >= 0;
      var partial = conversion ? coverage.conversion_complete !== true || ['roas','cpa','cvr'].indexOf(key) >= 0 && coverage.basic_complete !== true : coverage.basic_complete !== true;
      return h('div',{class:'nr-kpi','data-metric':key},h('dt',null,LABEL[key]),h('dd',null,value(p,key)),
        h('span',{class:'nr-delta'},changeText((comparison.changes || {})[key],key)),
        h('span',{class:'nr-kpi-note'},partial ? '확인된 범위 · 전체 수치 아님' : '선택 기간 전체 집계'));
    }
    function svg(tag,attrs) {
      var node = document.createElementNS('http://www.w3.org/2000/svg',tag);
      Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key,attrs[key]); }); return node;
    }
    function drawChart(report,key) {
      var detail = report.payload.details || {}, days = detail.daily || [], comparison = detail.comparison || {};
      var prior = comparison.status === 'ready' || comparison.basic_status === 'ready' ? comparison.daily || [] : [];
      var values = days.concat(prior).map(function (day) { return metric(day,key); }).filter(finite);
      if (!days.length || !values.length) return h('p',{class:'empty'},'일별 자료가 아직 저장되지 않았습니다. 누락은 0으로 표시하지 않습니다.');
      var max = Math.max.apply(null,values.concat([1])), width = 960, height = 220, left = 62, right = 16, top = 16, bottom = 32;
      var size = Math.max(days.length,prior.length,2);
      var graph = svg('svg',{viewBox:'0 0 ' + width + ' ' + height,role:'img','aria-label':LABEL[key] + ' 일별 추이. 점선은 비교 가능한 전기간, 끊긴 구간은 미확인입니다.'});
      for (var i = 0; i < 4; i++) {
        var y = top + i * (height-top-bottom)/3;
        graph.appendChild(svg('line',{x1:left,y1:y,x2:width-right,y2:y,class:'nr-gridline'}));
        var label = svg('text',{x:left-8,y:y+4,'text-anchor':'end',class:'nr-axis'}); label.textContent = Math.round(max * (1-i/3)).toLocaleString('ko-KR'); graph.appendChild(label);
      }
      function line(series,priorLine) {
        var points = [], dots = [];
        function flush() { if (points.length) graph.appendChild(svg('polyline',{points:points.join(' '),class:priorLine ? 'nr-line nr-prior' : 'nr-line'})); points = []; }
        series.forEach(function (day,index) {
          var n = metric(day,key), cov = day.coverage || {};
          if (n === null || cov.basic_complete !== true) { flush(); return; }
          var x = left + index*(width-left-right)/(size-1), y = top+(1-n/max)*(height-top-bottom);
          points.push(x + ',' + y); if (!priorLine) dots.push(svg('circle',{cx:x,cy:y,r:3,class:'nr-dot'}));
        });
        flush(); dots.forEach(function (dot) { graph.appendChild(dot); });
      }
      line(prior,true); line(days,false);
      [0,Math.floor((days.length-1)/2),days.length-1].forEach(function (index) {
        var text = svg('text',{x:left+index*(width-left-right)/(size-1),y:height-8,'text-anchor':'middle',class:'nr-axis'});
        text.textContent = (days[index].day || '').slice(5); graph.appendChild(text);
      });
      return h('div',{class:'nr-chart'},graph,h('p',{class:'hint'},'실선: 선택 기간' + (prior.length ? ' · 점선: 전기간(날짜 순서 비교)' : ' · 전기간 비교 자료 부족') +
        (prior.length && prior.length !== days.length ? ' · 선택 ' + days.length + '일 / 비교 ' + prior.length + '일로 기간 길이가 다릅니다.' : '') + ' · 미확인 날짜는 선을 잇지 않습니다.'));
    }
    function renderChart(report) {
      put($('reportChart'),h('div',{class:'nr-section-heading'},h('div',null,h('h3',null,'일별 성과 흐름'),h('p',{class:'hint'},'광고비·노출·클릭의 날짜별 변화를 확인하세요.')),
        h('div',{class:'chips','aria-label':'일별 차트 지표'},['spend','impressions','clicks'].map(function (key) { return h('button',{type:'button',class:'chip' + (chartMetric === key ? ' on' : ''),'aria-pressed':String(chartMetric === key),onclick:function () { chartMetric = key; renderChart(report); }},LABEL[key]); }))),drawChart(report,chartMetric));
    }
    function renderDetail(report,mark,ctx) {
      var p = report.payload || {}, period = p.period || {}, scope = report.scope || {}, detail = p.details || {}, comparison = detail.comparison || {};
      var available = p.format_version === 2 && Array.isArray(detail.daily);
      var chosen = selected;
      function switchScope(account) { if (fresh(mark,ctx) && displayed === report) open(chosen,account); }
      put($('reportDetail'),
        h('div',{class:'nr-detail-top'},h('button',{type:'button',class:'link',id:'reportBack',onclick:function () { selected = null; load(filter.page); }},'← 보고서 목록'),
          h('span',{class:'hint'},'광고주에게 보내기 전 내용과 집계 범위를 확인하세요.')),
        h('article',{class:'card nr-report'},
          h('header',{class:'nr-report-header'},h('div',null,h('p',{class:'nr-eyebrow'},'META I&C · NAVER ADS REPORT'),
            h('h2',{id:'reportDetailTitle'},report.company_name + ' ' + (period.kind === 'monthly' ? '월간' : '주간') + ' 보고서'),
            h('p',{class:'nr-subtitle'},env.periodText(period.start,period.end) + ' · 담당 ' + (report.owner && report.owner.name || '미확인'))),
            h('button',{type:'button',class:'btn primary',id:'reportPdfDownload',disabled:!available,onclick:function () { download(report,this,mark,ctx); }},'PDF 내려받기')),
          h('div',{class:'nr-scope-row'},h('div',{class:'chips','aria-label':'보고서 집계 범위'},
            h('button',{type:'button',class:'chip' + (scope.kind === 'account' ? ' on' : ''),'aria-pressed':String(scope.kind === 'account'),onclick:function () { switchScope(chosen.account_key); }},'이 광고 계정'),
            h('button',{type:'button',class:'chip' + (scope.kind === 'company' ? ' on' : ''),'aria-pressed':String(scope.kind === 'company'),onclick:function () { switchScope('company'); }},'업체 전체 합산')),
            statusChip(report.status)),
          h('p',{class:'nr-account-scope'},scope.kind === 'company' && detail.status === 'legacy_unavailable' ? '이전 판 · 포함 계정 상세 미보관' : scope.kind === 'company' ? '합산 ' + env.num((scope.accounts || []).length) + '개 계정 · ' +
              (scope.accounts || []).map(function (account) { return (account.account_name || '계정') + ' (' + (account.ad_account_no || '번호 미확인') + ')'; }).join(', ') :
              (scope.account_name || '계정 이름 미확인') + ' · 광고 계정 ID ' + (scope.ad_account_no || '미확인')),
          h('p',{class:'report-meta'},'저장된 ' + env.num(report.revision_no) + '판 · 자료 기준 ' + env.datedTime(report.generated_at)),
          report.status !== 'ready' ? h('div',{class:'nr-notice'},stateLabel(report.status) + '입니다. 아래 숫자는 확인된 자료의 합계이며 전체 기간 성과와 다를 수 있습니다. 미수집 항목은 —로 표시합니다.') : null,
          !available ? h('div',{class:'nr-notice'},'이전 형식으로 저장된 판입니다. 계정별 상세·일별 추이는 보관되지 않았습니다. 다음 보고서 재집계 때 새 판으로 확인할 수 있으며 이 판의 값을 현재 자료로 바꾸지 않습니다.') : null,
          h('section',{class:'nr-brief'},h('h3',null,'이번 기간, 세 줄로 보기'),
            (detail.briefing || []).length ? h('ol',null,detail.briefing.map(function (line) { return h('li',null,line); })) :
              h('p',null,'검증된 상세 자료가 부족해 요약을 작성하지 않았습니다.'),h('p',{class:'hint'},'저장된 숫자로 만든 요약입니다. 성과 원인이나 향후 매출을 추정하지 않습니다.')),
          h('dl',{class:'nr-kpis'},['spend','conversion_value','roas','cpa'].map(function (key) { return metricCard(report,key); })),
          h('p',{class:'nr-compare-note'},'비교 기간: ' + (comparison.period ? env.periodText(comparison.period.start,comparison.period.end) : '자료 미보관') +
            ' · 전주/전월 비교이며 이전 판 정정과 다릅니다. 비율 차이는 %p로 표시합니다.'),
          h('section',{id:'reportChart',class:'nr-chart-panel'}),
          h('dl',{class:'nr-secondary'},['impressions','clicks','ctr','cpc','conversions','cvr'].map(function (key) { return metricCard(report,key); })),
          h('p',{class:'hint'},'전환은 수집된 전환 지표이며 구매 건수와 다를 수 있습니다. ROAS·전환율·전환당 비용은 기본·전환이 함께 확인된 범위로 계산합니다.'),
          h('div',{class:'nr-notes-grid'},h('section',null,h('h3',null,'실제 관리 기록'),h('p',null,'이 기간·계정에 연결된 검증 가능한 관리 기록이 저장되지 않았습니다.'),h('span',{class:'hint'},'광고 설정을 바꿨거나 업무를 완료한 것으로 표시하지 않습니다.')),
            h('section',null,h('h3',null,'다음 관리 계획 · 광고주 확인 요청'),h('p',null,'담당자가 검토해 확정한 계획은 아직 없습니다.'),h('span',{class:'hint'},'추후 담당자 브리핑 기능에서 작성할 수 있도록 확장할 영역입니다.'))),
          h('details',{class:'nr-quality'},h('summary',null,'집계 범위 · 누락 · 정정 이력 확인'),
            env.validation(report),env.changes(report),
            h('p',{class:'report-meta'},'기본 지표 ' + env.num((p.coverage || {}).basic_complete_account_days) + '/' + env.num((p.coverage || {}).expected_account_days) +
              ' 계정×일 · 전환 지표 ' + env.num((p.coverage || {}).conversion_complete_account_days) + '/' + env.num((p.coverage || {}).expected_account_days) + ' 계정×일'),
            h('p',{class:'hint'},'누락된 일자나 지표는 0이 아닙니다. 부분 집계 PDF에도 미확인 범위를 표시합니다.'),
            h('details',{class:'nr-day-table'},h('summary',null,'일별 숫자 보기'),dailyTable(detail.daily || [])),history(report,mark,ctx)),
          h('footer',{class:'nr-report-footer'},'META I&C · 네이버 광고 성과 보고서',h('span',null,'다운로드는 발송이 아닙니다. 사본은 이후 정정되어도 자동 변경되지 않습니다.'))));
      renderChart(report);
    }
    function dailyTable(days) {
      return days.length ? h('table',null,h('thead',null,h('tr',null,['날짜','광고비','노출','클릭','전환','상태'].map(function (name) { return h('th',null,name); }))),
        h('tbody',null,days.map(function (day) { return h('tr',null,h('td',null,day.day),['spend','impressions','clicks','conversions'].map(function (key) { return h('td',{class:'num'},value(day,key)); }),h('td',null,stateLabel(day.status))); }))) : h('p',{class:'hint'},'저장된 일별 숫자가 없습니다.');
    }
    function history(report,mark,ctx) {
      var content = h('div'), loaded = false, section;
      section = h('details',{class:'report-history',ontoggle:function () {
        if (!section.open || loaded || !fresh(mark,ctx)) return;
        loaded = true; put(content,h('p',{class:'hint'},'정정 이력을 확인 중입니다…'));
        read();
      }},h('summary',null,'이전 판 · 정정 이력'),content);
      function read(before) {
        return env.api('GET','/reports/history?possibility_id=' + report.possibility_id + '&period_key=' + encodeURIComponent(report.period_key) + '&limit=20' +
          (before ? '&before_report_id=' + before : '')).then(function (data) {
          if (!fresh(mark,ctx)) return;
          put(content,h('p',{class:'hint'},'당시 저장된 업체 합산 이력입니다. 계정별 상세가 보관된 판만 계정 범위로 열 수 있습니다.'),
            (data.items || []).map(function (item) { return h('div',{class:'nr-history-row'},h('span',null,env.num(item.revision_no) + '판 · ' + env.datedTime(item.generated_at) + ' · ' + stateLabel(item.status)),
              h('button',{type:'button',class:'btn sm',onclick:function () { open(Object.assign({},selected,{report_id:item.report_id}),report.scope.account_key); }},'이 판 보기')); }),
            data.next_before_report_id ? h('button',{type:'button',class:'btn sm',onclick:function () { read(data.next_before_report_id); }},'더 이전 판') : null);
        },function (error) { if (fresh(mark,ctx)) { if (env.denied(error)) env.purge(error); else { loaded = false; put(content,h('p',{class:'hint'},'이력을 확인하지 못했습니다. 접었다 다시 열어 주세요.')); } } });
      }
      return section;
    }
    function download(report,button,mark,ctx) {
      if (!fresh(mark,ctx) || displayed !== report || button.disabled) return;
      button.disabled = true; button.textContent = '권한·보고서 확인 중…';
      env.api('GET',detailPath(report.report_id,report.scope.account_key)).then(function (verified) {
        if (!fresh(mark,ctx) || displayed !== report) return;
        if (!sameEdition(report,verified)) throw new Error('report-changed');
        if (!window.NaverReportPDF) throw new Error('pdf-unavailable');
        button.textContent = 'PDF 파일 생성 중…';
        return window.NaverReportPDF.download(verified,{isCurrent:function () { return fresh(mark,ctx) && displayed === report; }}).then(function () {
          if (fresh(mark,ctx) && displayed === report) env.toast('PDF 파일을 내려받았습니다. 광고주에게 자동 발송하지 않았습니다.');
        });
      }).catch(function (error) {
        if (!fresh(mark,ctx)) return;
        if (env.denied(error)) { env.purge(error); return; }
        env.toast(error.message === 'report-changed' ? '보고서 정보가 바뀌었습니다. 새로고침 후 다시 내려받아 주세요.' : 'PDF를 만들지 못했습니다. 파일·글꼴 연결과 로그인 상태를 확인한 뒤 다시 시도해 주세요.');
      }).then(function () { if (fresh(mark,ctx) && displayed === report) { button.disabled = false; button.textContent = 'PDF 내려받기'; } });
    }
    return {load:load,company:function (pid) { filter.pid = pid; filter.q = ''; filter.page = 0; selected = null; displayed = null; },
      reset:function () { epoch++; clearTimeout(searchTimer); selected = null; displayed = null; lastList = null; listReady = false; listContext = null; filter = {kind:'weekly',anchor:'',requestAnchor:'',q:'',page:0,pid:null}; anchors = {}; if (initialized) controls(); put($('reportDetail')); put($('reportUnlinked')); }};
  }
  window.NaverReports = {create:create,model:{query:query,changeText:changeText,sameEdition:sameEdition,metric:metric}};
}());
