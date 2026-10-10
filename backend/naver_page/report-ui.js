/* 저장된 같은 판만 표시하는 계정별 보고서. API/권한/캐시는 기존 관제 입구가 제공한다. */
(function () {
  'use strict';
  var LABEL = {spend:'광고비',conversion_value:'광고 전환가치',roas:'ROAS',cpa:'CPA',impressions:'노출수',clicks:'클릭수',ctr:'CTR',cpc:'CPC',conversions:'전환수',cvr:'CVR',cpm:'CPM',value_per_conversion:'전환당 전환가치',spend_per_day:'일평균 광고비',clicks_per_day:'일평균 클릭수',impressions_per_day:'일평균 노출수',conversions_per_day:'일평균 전환수',value_per_day:'일평균 전환가치'};
  var STATUS = {ready:'생성 완료',partial:'부분 집계',collecting:'수집 중',not_generated:'아직 생성되지 않음'};
  var LAYOUTS = {a:'A · 카드 대시보드',b:'B · 데이터 분석형',c:'C · 전략 브리프'};
  function finite(value) { return typeof value === 'number' && isFinite(value); }
  function round(value) { return Number(value.toFixed(2)).toLocaleString('ko-KR'); }
  function metric(payload, key) {
    var enriched = payload && payload.details && payload.details.enrichment;
    var item = enriched && Array.isArray(enriched.metrics) && enriched.metrics.find(function (row) { return row.key === key; });
    if (item) return finite(item.current) ? item.current : null;
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
      JSON.stringify(a.annotations) === JSON.stringify(b.annotations) &&
      ['company_name','owner','generated_at','period_key','status','possibility_id'].every(function (key) { return JSON.stringify(a[key]) === JSON.stringify(b[key]); });
  }
  function create(env) {
    var h = env.h, put = env.put, $ = env.$;
    var filter = {kind:'weekly',anchor:'',requestAnchor:'',q:'',page:0,pid:null}, anchors = {}, epoch = 0, searchTimer;
    var selected = null, displayed = null, initialized = false, chartMetric = 'spend', lastList = null, listReady = false, listContext = null;
    var displayedMark = null, displayedContext = null;
    var sharedView = false, drafts = {}, savingNotes = {};
    var layout = 'a', layoutGeneration = 0;
    try { var preferred = window.sessionStorage && window.sessionStorage.getItem('naver-report-layout'); if (Object.prototype.hasOwnProperty.call(LAYOUTS,preferred)) layout = preferred; } catch (_) {}
    function noteKey(report) { return report.report_id + '|' + report.scope.account_key + '|' + report.revision_fingerprint; }
    function dirty() { return Object.keys(drafts).some(function (key) { return drafts[key].dirty; }); }
    function exportReady(report) { var key = noteKey(report); return !savingNotes[key] && !(drafts[key] && drafts[key].dirty); }
    if (window.addEventListener) window.addEventListener('beforeunload',function (event) { if (dirty()) { event.preventDefault(); event.returnValue = ''; } });
    function context() { return env.context(); }
    function fresh(mark, ctx) { return mark === epoch && ctx === context() && env.active(); }
    function notesCapability(body) {
      if (!body || !displayed || !fresh(displayedMark,displayedContext)) return false;
      var a = displayed.annotations || {};
      if (body.report_id !== displayed.report_id || body.account_key !== displayed.scope.account_key ||
          body.revision_fingerprint !== displayed.revision_fingerprint || !Number.isSafeInteger(body.expected_version) || body.expected_version !== a.version) return false;
      if (body.action === 'save') return a.can_edit === true && !!body.document && typeof body.document === 'object' && !Array.isArray(body.document);
      return body.action === 'approve' && body.document === undefined && a.can_approve === true && a.state === 'draft' && !(drafts[noteKey(displayed)] && drafts[noteKey(displayed)].dirty);
    }
    function stateLabel(status) { return STATUS[status] || '집계 상태 미확인'; }
    function value(payload, key) {
      var n = metric(payload, key);
      if (n === null) return '—';
      if (['spend','conversion_value','cpa','cpc'].indexOf(key) >= 0) return env.won(n);
      return round(n) + (['ctr','roas','cvr'].indexOf(key) >= 0 ? '%' : '');
    }
    function statusChip(report) {
      var status = typeof report === 'string' ? report : report.status;
      var collection = report && report.collection_status;
      var labels = {complete:'기본·전환 자료 완결',conversion_unconfirmed:'기본 자료 완결 · 전환 산정 근거 미확인',basic_incomplete:'기본 자료 누락 · 점검 필요'};
      return h('span',{class:'pill ' + (collection === 'complete' || !collection && status === 'ready' ? 'p-green' : collection === 'basic_incomplete' || collection === 'conversion_unconfirmed' || status === 'partial' ? 'p-amber' : 'p-gray')},labels[collection] || stateLabel(status));
    }
    function confirmedTime(at) { return at ? env.datedTime(at) : '미확인'; }
    function refreshLabel(refresh) {
      if (refresh && refresh.scope === 'current' && refresh.status === 'pending' && refresh.conversion_response && refresh.conversion_response.status === 'complete') return '수치 응답 대조 완료 · 전환 산정 근거 확인 필요';
      return {complete:'기본·전환 전체 재대조 완료',pending:'재대조 대기',failed:'재대조 실패 · 확인 필요',updating:'정정 집계 갱신 중'}[(refresh || {}).status] || '재대조 상태 미확인';
    }
    function responseSummary(refresh, detailed) {
      var response = refresh && refresh.scope === 'current' && refresh.conversion_response;
      if (!response || !finite(response.expected_account_days) || response.expected_account_days <= 0) return null;
      var text = '현재 원천 전환 수치 응답 ' + env.num(response.received_account_days) + '/' + env.num(response.expected_account_days) + ' 계정×일';
      if (!detailed) return h('span',{class:'w'},text);
      return h('div',{'aria-label':'현재 원천 전환 응답 범위'},h('p',{class:'hint nr-refresh-meta'},text + ' · ' + (response.status === 'complete' ? '응답 수집 완료' : '응답 미완결')),
        h('p',{class:'hint'},'0 응답 ' + env.num(response.zero_account_days) + ' · 양수 응답 ' + env.num(response.positive_account_days) +
          ' · 미제공·유효하지 않은 값 ' + env.num(response.missing_or_null_account_days) + ' · 최신 수집 근거 미확인 ' + env.num(response.source_unverified_account_days) + ' · 기본 자료 미완결 ' + env.num(response.basic_incomplete_account_days)),
        h('p',{class:'hint'},'숫자 0은 네이버가 반환한 전환수·전환금액이 모두 0인 경우입니다. 응답 수집 완료는 전환 추적 설치·정상 동작을 뜻하지 않습니다. 이 최신 상태를 저장판 수치나 PDF에 합산하지 않습니다.'));
    }
    function refreshSummary(report) {
      var refresh = report.refresh || {};
      return h('section',{class:'nr-refresh-summary','aria-label':'성과 자료 갱신 확인'},
        h('p',{class:'hint nr-refresh-meta'},(refresh.scope === 'current' ? '현재판의 최신 확인 상태 · ' : '선택한 저장판의 확인 상태 · ') + refreshLabel(refresh)),
        h('p',{class:'hint nr-refresh-meta'},'최근 성과 수집 ' + confirmedTime(refresh.source_collected_at) + ' · 기본·전환 전체 재대조 성공 ' + confirmedTime(refresh.last_success_at)),
        h('p',{class:'hint nr-refresh-meta'},'최근 재대조 시도 ' + confirmedTime(refresh.last_attempt_at) + ' · 수치판 생성 ' + confirmedTime(report.generated_at)),
        responseSummary(refresh,true),
        h('p',{class:'hint'},'수치는 선택한 저장판 기준입니다. 전체 재대조 성공은 선택 범위의 모든 날짜에서 기본·전환 자료가 확인된 경우입니다. 최근 수집 시각은 일부 자료의 읽기 완료 시각이며 전체 기간 완결을 뜻하지 않습니다. 조회·새로고침은 수집을 시작하지 않습니다.'));
    }
    function format(n,unit,signed) {
      if (!finite(n)) return '—';
      var result = unit === 'money' ? env.won(n) : round(n) + (unit === 'percent' ? '%' : '');
      return signed && n > 0 ? '+' + result : result;
    }
    function enrichment(report) { return report.payload && report.payload.details && report.payload.details.enrichment || {}; }
    function scopeText(scope) {
      scope = scope || {};
      return (scope.family === 'paired' ? '공동 ' : '') + (finite(scope.account_days) ? env.num(scope.account_days) : '—') + '/' +
        (finite(scope.expected_account_days) ? env.num(scope.expected_account_days) : '—') + ' 계정×일' + (scope.complete === true ? ' · 완결' : ' · 확인분');
    }
    function approvedShared(report) {
      var a = report.annotations || {}, s = a.shared, m = s && s.metadata;
      return a.state === 'approved' && s && s.state === 'approved' && s.version === a.version && m &&
        m.report_id === report.report_id && m.account_key === report.scope.account_key && m.revision_fingerprint === report.revision_fingerprint ? s : null;
    }
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
            h('td',null,statusChip(row),h('span',{class:'w'},refreshLabel(row.refresh)),responseSummary(row.refresh,false),h('span',{class:'w'},'성과 수집 ' + confirmedTime((row.refresh || {}).source_collected_at)),
              h('span',{class:'w'},'기본·전환 전체 재대조 성공 ' + confirmedTime((row.refresh || {}).last_success_at)),
              h('span',{class:'w'},'수치판 생성 ' + confirmedTime(row.generated_at))),
            h('td',null,h('button',{type:'button',class:'btn sm',disabled:!row.report_id,'aria-label':row.company_name + ' ' + (row.ad_account_no || row.account_name || '') + ' 보고서 보기',onclick:function () { if (listReady && !selected && context() === ctx && env.active() && lastList === data) open(row,row.account_key); }},row.report_id ? '보고서 보기' : '생성 대기'))];
          cells.forEach(function (cell,index) { cell.setAttribute('data-label',labels[index]); });
          return h.apply(null,['tr',{'data-account-key':row.account_key,'data-report':row.report_id}].concat(cells));
        })))) : h('div',{class:'card empty'},filter.q ? '검색 조건에 맞는 관리 계정이 없습니다. 업체명이나 광고 계정 ID를 다시 확인해 주세요.' : '현재 담당 범위에 연결된 실관리 광고 계정이 없습니다. 이관 현황에서 계정 연결을 확인해 주세요.'));
      function page(next) { if (listReady && !selected && context() === ctx && env.active() && lastList === data) load(next); }
      put($('reportsPages'),filter.page > 0 ? h('button',{type:'button',class:'btn',onclick:function () { page(data.page-1); }},'이전') : null,
        h('span',{class:'hint'},String(filter.page+1) + '페이지'),data.next_page !== null && typeof data.next_page === 'number' ?
          h('button',{type:'button',class:'btn',onclick:function () { page(data.next_page); }},'다음') : null);
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
      var row = (enrichment(report).metrics || []).find(function (item) { return item.key === key; });
      if (row) return h('div',{class:'nr-kpi','data-metric':key},h('dt',null,LABEL[key]),h('dd',null,format(row.current,row.unit)),
        h('span',{class:'nr-delta'},row.status === 'ready' || row.status === 'zero_denominator' ?
          (row.percentage_points && finite(row.absolute) ? format(row.absolute,'decimal',true) + '%p' : finite(row.percent) ? format(row.percent,'percent',true) : row.comparison_reason || '증감률 산출 불가') : row.comparison_reason || '비교 자료 부족'),
        h('span',{class:'nr-kpi-note'},scopeText(row.scope)));
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
    function drawChart(report,key,printing) {
      var detail = report.payload.details || {}, days = detail.daily || [], comparison = detail.comparison || {};
      var conversion = key === 'conversions' || key === 'roas';
      var comparable = conversion ? comparison.conversion_status === 'ready' && (key !== 'roas' || comparison.basic_status === 'ready') : comparison.basic_status === 'ready';
      var prior = comparison.status === 'ready' || comparable ? comparison.daily || [] : [];
      var values = days.concat(prior).map(function (day) { return metric(day,key); }).filter(finite);
      if (!days.length || !values.length) return h('p',{class:'empty'},'일별 자료가 아직 저장되지 않았습니다. 누락은 0으로 표시하지 않습니다.');
      var max = Math.max.apply(null,values.concat([1])), width = printing ? 480 : 960, height = 220, left = 62, right = 16, top = 16, bottom = 32;
      left = Math.max(left,Math.min(width * .4,Math.round(max).toLocaleString('ko-KR').length * (printing ? 9 : 6) + 16));
      var size = Math.max(days.length,prior.length,2);
      var graph = svg('svg',{viewBox:'0 0 ' + width + ' ' + height,class:printing ? 'nr-print-chart' : 'nr-preview-chart',role:'img','aria-label':LABEL[key] + ' 일별 추이. 점선은 비교 가능한 전기간, 끊긴 구간은 미확인입니다.'});
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
          var complete = conversion ? cov.conversion_complete === true && (key !== 'roas' || cov.basic_complete === true) : cov.basic_complete === true;
          if (n === null || !complete) { flush(); return; }
          if (index && Date.parse(day.day) - Date.parse(series[index-1].day) !== 86400000) flush();
          var x = left + index*(width-left-right)/(size-1), y = top+(1-n/max)*(height-top-bottom);
          points.push(x + ',' + y); if (!priorLine) { var dot = svg('circle',{cx:x,cy:y,r:3,class:'nr-dot'}), title = svg('title'); title.textContent = day.day + ' · ' + LABEL[key] + ' ' + value(day,key); dot.appendChild(title); dots.push(dot); }
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
    function renderChart(report,mark,ctx) {
      put($('reportChart'),h('div',{class:'nr-section-heading'},h('div',null,h('h3',null,'일별 성과 흐름'),h('p',{class:'hint'},'저장된 일별 수치입니다. 전환·ROAS의 미완결 날짜는 선으로 잇지 않습니다.')),
        h('div',{class:'chips','aria-label':'일별 차트 지표'},['spend','impressions','clicks','conversions','roas'].map(function (key) { return h('button',{type:'button',class:'chip' + (chartMetric === key ? ' on' : ''),'aria-pressed':String(chartMetric === key),onclick:function () { if (!fresh(mark,ctx) || displayed !== report) return; chartMetric = key; renderChart(report,mark,ctx); }},LABEL[key]); }))),drawChart(report,chartMetric));
    }
    function qualityCards(report) {
      var q = enrichment(report).quality || {};
      return h('section',{class:'nr-quality-cards','aria-label':'자료 완결 범위'},[['basic','기본 자료 완결','노출 · 클릭 · 광고비'],['conversion','전환 자료 완결','전환 · 광고 전환가치'],['paired','효율 계산 공동 범위','기본과 전환이 함께 확인된 계정×일']].map(function (item) {
        var block = q[item[0]] || {};
        return h('article',{class:'nr-quality-card'},h('h3',null,item[1]),h('strong',null,(finite(block.count) ? env.num(block.count) : '—') + '/' +
          (finite(q.expected_account_days) ? env.num(q.expected_account_days) : '—') + ' 계정×일'),h('span',null,format(block.percent,'percent') + ' · ' + (block.complete === true ? '완결' : '미완결·미확인')),h('p',{class:'hint'},item[2]));
      }));
    }
    function comparisonTable(metrics) {
      return h('div',{class:'nr-scroll-table'},h('table',{class:'nr-metric-table'},h('thead',null,h('tr',null,['지표','현재','이전','절대 변화','상대 변화','차이(%p)','계산·비교 범위'].map(function (label) { return h('th',null,label); }))),
        h('tbody',null,(metrics || []).filter(function (item) { return Object.prototype.hasOwnProperty.call(LABEL,item.key); }).map(function (item) {
          var comparable = item.status === 'ready' || item.status === 'zero_denominator';
          return h('tr',{'data-metric':item.key},h('th',{scope:'row'},LABEL[item.key]),h('td',{class:'num'},format(item.current,item.unit)),h('td',{class:'num'},format(item.previous,item.unit)),
            h('td',{class:'num'},comparable && !item.percentage_points ? format(item.absolute,item.unit,true) : '—'),h('td',{class:'num'},comparable ? format(item.percent,'percent',true) : '—'),
            h('td',{class:'num'},comparable && item.percentage_points && finite(item.absolute) ? format(item.absolute,'decimal',true) + '%p' : '—'),
            h('td',null,scopeText(item.scope),item.comparison_reason ? h('span',{class:'w'},item.comparison_reason) : null));
        }))));
    }
    function metricKeys(keys) { return Array.isArray(keys) && keys.length ? h('p',{class:'nr-evidence'},'근거 지표: ' + keys.filter(function (key) { return LABEL[key]; }).map(function (key) { return LABEL[key]; }).join(' · ')) : null; }
    function feedback(report) {
      var f = enrichment(report).feedback || {};
      return h('section',{class:'nr-feedback'},h('h3',null,'수치 근거와 확인할 내용'),h('p',{class:'hint'},'관측 사실, 원인 가설, 예정 행동을 구분합니다. 가설이나 권장 행동은 완료된 업무가 아닙니다.'),
        h('div',{class:'nr-feedback-grid'},[['facts','관측 사실'],['hypotheses','원인 가설 · 추가 확인'],['actions','권장 행동']].map(function (group) {
          return h('article',null,h('h4',null,group[1]),(f[group[0]] || []).length ? h('ul',null,f[group[0]].map(function (item) {
            var e = item.evidence || {};
            return h('li',null,h('p',null,item.text || ''),metricKeys(item.metric_keys),group[0] === 'facts' && e.scope ? h('p',{class:'nr-evidence'},'근거 범위: ' + e.scope + ' · ' + (finite(e.account_days) ? env.num(e.account_days) : '—') + '/' + (finite(e.expected_account_days) ? env.num(e.expected_account_days) : '—') + ' 계정×일') : null,
              group[0] === 'hypotheses' ? [item.alternative ? h('p',{class:'hint'},'다른 가능성: ' + item.alternative) : null,item.required_evidence ? h('p',{class:'hint'},'필요 근거: ' + (Array.isArray(item.required_evidence) ? item.required_evidence.join(' · ') : item.required_evidence)) : null,item.verification ? h('p',{class:'hint'},'확인 방법: ' + item.verification) : null] : null,
              group[0] === 'actions' ? [item.reason ? h('p',{class:'hint'},'이유: ' + item.reason) : null,h('p',{class:'hint'},'담당 ' + (item.owner || '미정') + ' · 기한 ' + (item.due_date || '미정') + ' · 우선순위 ' + ({high:'높음',medium:'보통',low:'낮음'}[item.priority] || '미정') + ' · ' + (item.approval_status === 'approved' ? '승인됨' : '검토 필요') + ' · ' + (item.status === 'completed' ? '완료' : '예정·미완료'))] : null);
          })) : h('p',{class:'hint'},'이 판에 저장된 내용이 없습니다.'));
        })));
    }
    function contributions(report) {
      var rows = report.scope.kind === 'company' ? report.scope.contributions : null;
      if (!Array.isArray(rows)) return null;
      function find(row,key) { return (row.metrics || []).find(function (item) { return item.key === key; }) || {}; }
      return h('section',{class:'nr-contributions'},h('h3',null,'업체 합산 · 계정별 기여'),h('p',{class:'hint'},'동일 보고서 판에 포함된 계정입니다. 효율은 공동 합계로 계산하며 계정 비율의 단순평균이 아닙니다. 미완결 기여 비중은 —로 표시합니다.'),
        h('div',{class:'nr-scroll-table'},h('table',null,h('thead',null,h('tr',null,['계정','광고비','광고비 비중','전환수','전환 비중','광고 전환가치','ROAS','CPA'].map(function (label) { return h('th',null,label); }))),h('tbody',null,rows.map(function (row) {
          return h('tr',null,h('th',{scope:'row'},row.account_name || '계정 이름 미확인',h('span',{class:'w'},'ID ' + (row.ad_account_no || '미확인'))),
            h('td',{class:'num'},format(find(row,'spend').current,'money')),h('td',{class:'num'},format((row.shares || {}).spend,'percent')),
            h('td',{class:'num'},format(find(row,'conversions').current,'number')),h('td',{class:'num'},format((row.shares || {}).conversions,'percent')),
            h('td',{class:'num'},format(find(row,'conversion_value').current,'money')),h('td',{class:'num'},format(find(row,'roas').current,'percent')),h('td',{class:'num'},format(find(row,'cpa').current,'money')));
        })))),rows.map(function (row) { return h('details',null,h('summary',null,(row.account_name || '계정') + ' · 17개 지표와 범위'),comparisonTable(row.metrics)); }));
    }
    function targetSection(report,doc) {
      var targets = doc && doc.targets || {}, metrics = enrichment(report).metrics || [];
      return h('section',{class:'nr-targets'},h('h3',null,'저장된 목표 대비'),h('p',{class:'hint'},targets.source ? '목표 출처: ' + targets.source : '목표 출처가 저장되지 않아 판정을 보류합니다. 임의 목표를 설정하지 않습니다.'),
        h('div',{class:'nr-target-grid'},['spend_per_day','cpa','roas'].map(function (key) {
          var item = metrics.find(function (m) { return m.key === key; }) || {}, target = targets[key], ready = finite(target) && !!targets.source && item.scope && item.scope.complete === true && finite(item.current);
          var description = !finite(target) ? '목표 미설정' : !ready ? '자료·목표 출처 미확인 · 판정 보류' : key === 'roas' ? (item.current >= target ? '목표 이상' : '목표 미달') : (item.current <= target ? '목표 이내' : '목표 초과');
          return h('article',null,h('h4',null,LABEL[key]),h('strong',null,format(item.current,key === 'roas' ? 'percent' : 'money')),h('p',null,'목표 ' + format(target,key === 'roas' ? 'percent' : 'money') + ' · ' + description),h('span',{class:'hint'},scopeText(item.scope)));
        })));
    }
    function noteDocument(raw) {
      raw = raw || {}; var targets = raw.targets || {};
      return {internal_note:raw.internal_note || '',client_feedback:raw.client_feedback || '',shared_comment:raw.shared_comment || '',next_plan:raw.next_plan || '',plan_due:raw.plan_due || null,
        targets:{cpa:finite(targets.cpa) ? targets.cpa : null,roas:finite(targets.roas) ? targets.roas : null,spend_per_day:finite(targets.spend_per_day) ? targets.spend_per_day : null,source:targets.source || ''}};
    }
    function sharedContent(report,doc,candidate) {
      return h('section',{class:'nr-shared-content'},h('h3',null,candidate ? '저장 후 승인할 공유 문안 미리보기' : '승인된 공유 문안'),
        doc ? [h('p',{class:'nr-preserve'},doc.shared_comment || '공유 코멘트가 없습니다.'),h('h4',null,'다음 관리 계획'),h('p',{class:'nr-preserve'},doc.next_plan || '확정된 다음 계획이 없습니다.'),h('p',{class:'hint'},'계획 기한: ' + (doc.plan_due || '미정') + ' · 계획 기록은 업무 완료를 뜻하지 않습니다.')] : h('div',{class:'nr-notice'},'현재 수치판·문안판에 승인된 공유 문안이 없습니다. PDF에도 미확정 상태로 표시합니다.'),
        !candidate && doc ? h('p',{class:'hint'},'공유 문안 ' + env.num(doc.version) + '판 · 승인 시각 ' + env.datedTime(doc.approved_at)) : null);
    }
    function notesHistory(a) {
      var rows = Array.isArray(a.history) ? a.history : a.history && a.history.items || [];
      return h('details',{class:'nr-note-history'},h('summary',null,'문안 변경·승인 이력 · 내부용'),rows.slice(0,20).map(function (item) {
        var doc = noteDocument(item.document), author = item.author || {};
        return h('details',null,h('summary',null,'문안 ' + env.num(item.version) + '판 · ' + (item.state === 'approved' ? '공유 승인' : '저장·초안') + ' · ' + env.datedTime(author.at || item.approved_at)),
          h('p',null,'작성자 ID ' + (author.actor == null ? '미보관' : env.num(author.actor)) + ' · 작성 ' + env.datedTime(author.at)),
          h('p',null,'승인자 ID ' + (item.approved_by == null ? '미승인' : env.num(item.approved_by)) + ' · 승인 ' + env.datedTime(item.approved_at)),
          h('h4',null,'당시 내부 메모'),h('p',{class:'nr-preserve'},doc.internal_note || '미작성'),h('h4',null,'당시 광고주 질문·요청 · 내부 기록'),h('p',{class:'nr-preserve'},doc.client_feedback || '미작성'),
          h('h4',null,'당시 공유 코멘트'),h('p',{class:'nr-preserve'},doc.shared_comment || '미작성'),h('h4',null,'당시 다음 계획'),h('p',{class:'nr-preserve'},doc.next_plan || '미작성'),h('p',null,'계획 기한 ' + (doc.plan_due || '미정')),
          h('p',null,'목표: CPA ' + format(doc.targets.cpa,'money') + ' · ROAS ' + format(doc.targets.roas,'percent') + ' · 일평균 광고비 ' + format(doc.targets.spend_per_day,'money')),
          h('p',{class:'nr-preserve'},'목표 출처: ' + (doc.targets.source || '미작성')));
      }),a.history && a.history.next_before_version ? h('p',{class:'hint'},'최근 20개 문안 이력을 표시합니다.') : null);
    }
    function annotations(report,mark,ctx) {
      var a = report.annotations || {}, key = noteKey(report), saved = noteDocument(a.document), draft = drafts[key];
      if (!draft) draft = drafts[key] = {document:noteDocument(a.document),baseVersion:a.version || 0,dirty:false};
      if (!draft.dirty) { draft.document = noteDocument(a.document); draft.baseVersion = a.version || 0; }
      var stale = draft.baseVersion !== (a.version || 0), busy = !!savingNotes[key];
      var invalid = Object.keys(draft.invalidTargets || {}).some(function (field) { return draft.invalidTargets[field]; });
      var missingSource = ['cpa','roas','spend_per_day'].some(function (field) { return finite(draft.document.targets[field]); }) && !draft.document.targets.source.trim();
      function current() { return fresh(mark,ctx) && displayed === report; }
      function update() {
        if (!current()) return;
        draft.dirty = JSON.stringify(draft.document) !== JSON.stringify(saved);
        var pdfButton = $('reportPdfDownload'); if (pdfButton) pdfButton.disabled = report.payload.format_version !== 2 || !Array.isArray(report.payload.details.daily) || !exportReady(report);
        if (!$('reportNotesStatus')) return;
        var invalid = Object.keys(draft.invalidTargets || {}).some(function (key) { return draft.invalidTargets[key]; }), missingSource = ['cpa','roas','spend_per_day'].some(function (key) { return finite(draft.document.targets[key]); }) && !draft.document.targets.source.trim();
        $('reportNotesStatus').textContent = stale ? '다른 변경이 저장되었습니다. 입력 초안을 버리고 최신 문안을 확인해 주세요.' : draft.dirty ? '저장하지 않은 입력 초안입니다. 공유·PDF에는 포함되지 않습니다.' : a.state === 'approved' ? '현재 문안이 공유 승인되었습니다.' : '저장된 문안은 공유 승인 전입니다.';
        if (invalid || missingSource) $('reportNotesStatus').textContent = invalid ? '목표는 0 이상의 유효한 숫자로 입력해 주세요.' : '목표 수치를 저장하려면 목표 출처·합의 기준을 입력해 주세요.';
        $('reportNotesSave').disabled = busy || !a.can_edit || !draft.dirty || stale || invalid || missingSource;
        $('reportNotesApprove').disabled = busy || !a.can_approve || draft.dirty || stale || a.state !== 'draft';
        ['internal_note','client_feedback','shared_comment','next_plan','plan_due'].forEach(function (field) { $('reportNote-' + field).disabled = busy || !a.can_edit || stale; });
        ['cpa','roas','spend_per_day','source'].forEach(function (field) { $('reportTarget-' + field).disabled = busy || !a.can_edit || stale; });
        put($('reportNotesCandidate'),sharedContent(report,draft.document,true));
      }
      function field(key,label,max,type) {
        var attrs = {id:'reportNote-' + key,maxlength:max,'aria-label':label,disabled:busy || !a.can_edit || stale,oninput:function () { if (!current() || savingNotes[noteKey(report)] || !a.can_edit || stale) return; draft.document[key] = this.value || (key === 'plan_due' ? null : ''); update(); }};
        var input = h(type === 'date' ? 'input' : 'textarea',Object.assign(attrs,type === 'date' ? {type:'date'} : {rows:4})); input.value = draft.document[key] || '';
        return h('label',{class:'nr-note-field'},h('span',null,label),input);
      }
      function targetField(key,label) {
        var input = h('input',{id:'reportTarget-' + key,type:'number',min:0,step:'any','aria-label':label,disabled:busy || !a.can_edit || stale,oninput:function () {
          if (!current() || savingNotes[noteKey(report)] || !a.can_edit || stale) return;
          var n = this.value === '' ? null : Number(this.value); draft.invalidTargets = draft.invalidTargets || {}; draft.invalidTargets[key] = this.value !== '' && (!finite(n) || n < 0 || n > Number.MAX_SAFE_INTEGER); draft.document.targets[key] = n; update();
        }}); input.value = draft.document.targets[key] === null ? '' : draft.document.targets[key];
        return h('label',{class:'nr-note-field'},h('span',null,label),input);
      }
      var source = h('textarea',{id:'reportTarget-source',maxlength:500,rows:2,'aria-label':'목표 출처·합의 기준',disabled:busy || !a.can_edit || stale,oninput:function () { if (current() && !savingNotes[key] && a.can_edit && !stale) { draft.document.targets.source = this.value; update(); } }}); source.value = draft.document.targets.source;
      function mutate(action) {
        if (!current() || busy || savingNotes[key] || stale || action === 'save' && (!a.can_edit || !draft.dirty || $('reportNotesSave').disabled) || action === 'approve' && (!a.can_approve || draft.dirty || a.state !== 'draft')) return;
        var body = {report_id:report.report_id,account_key:report.scope.account_key,revision_fingerprint:report.revision_fingerprint,expected_version:a.version || 0,action:action};
        if (action === 'save') body.document = noteDocument(draft.document);
        busy = true; savingNotes[key] = true; update(); $('reportNotesStatus').textContent = action === 'save' ? '문안을 저장하고 같은 판을 다시 확인 중입니다…' : '공유 승인 후 같은 판을 다시 확인 중입니다…';
        env.api('POST','/reports/notes',body).then(function () {
          if (!current()) return;
          return env.api('GET',detailPath(report.report_id,report.scope.account_key)).then(function (verified) {
            if (!current()) return;
            if (verified.report_id !== report.report_id || verified.revision_fingerprint !== report.revision_fingerprint || verified.scope.account_key !== report.scope.account_key) throw new Error('report-changed');
            delete drafts[key]; delete savingNotes[key]; displayed = verified; renderDetail(verified,mark,ctx); env.onDetailVerified(verified);
            env.toast(action === 'save' ? '문안을 저장했습니다. 공유하려면 내용을 검토해 승인해 주세요.' : '현재 수치판·문안판의 공유를 승인했습니다.');
          });
        }).catch(function (error) {
          if (!current()) return;
          busy = false; delete savingNotes[key]; if (env.denied(error)) { env.purge(error); return; } update();
          var message = error.status === 409 || error.message === 'report-changed' ? '수치판 또는 문안판이 변경되었습니다. 새로 확인한 뒤 저장해 주세요. 입력 초안은 이 브라우저에 남아 있습니다.' : '문안을 저장·승인하지 못했습니다. 입력 내용과 연결 상태를 확인해 주세요.';
          if ($('reportNotesStatus')) $('reportNotesStatus').textContent = message; else env.toast(message);
        }).then(function () { delete savingNotes[key]; });
      }
      return h('section',{class:'nr-annotations'},h('h3',null,'담당자 메모 · 공유 코멘트 · 다음 계획'),h('p',{class:'hint'},'수치판 ' + env.num(report.revision_no) + '판 / 문안 ' + env.num(a.version || 0) + '판 · ' + ({empty:'작성 전',draft:'공유 검토 전',approved:'공유 승인'}[a.state] || '상태 미확인') + ' · 수치나 문안을 바꾸면 새 공유 승인이 필요합니다.'),
        a.author ? h('p',{class:'hint'},'작성자 ID ' + env.num(a.author.actor) + ' · 작성 ' + env.datedTime(a.author.at) + (a.approved_by != null ? ' · 승인자 ID ' + env.num(a.approved_by) + ' · 승인 ' + env.datedTime(a.approved_at) : ' · 공유 미승인')) : null,
        h('div',{class:'nr-note-grid'},field('internal_note','담당자 내부 메모 · 공유/PDF 제외',1000),field('client_feedback','광고주에게 받은 질문·요청(내부 기록)',1000),field('shared_comment','공유용 코멘트',2000),field('next_plan','다음 관리 계획',1000)),field('plan_due','계획 기한',10,'date'),
        h('div',{class:'nr-target-inputs'},targetField('spend_per_day','일평균 광고비 목표(원)'),targetField('cpa','CPA 목표(원 이하)'),targetField('roas','ROAS 목표(% 이상)')),h('label',{class:'nr-note-field'},h('span',null,'목표 출처·합의 기준'),source),
        h('p',{id:'reportNotesStatus',class:'nr-notice','aria-live':'polite'},stale ? '다른 변경이 저장되었습니다. 입력 초안을 버리고 최신 문안을 확인해 주세요.' : draft.dirty ? '저장하지 않은 입력 초안입니다. 공유·PDF에는 포함되지 않습니다.' : a.state === 'approved' ? '현재 문안이 공유 승인되었습니다.' : '저장 후 공유할 내용과 목표 출처를 검토하고 승인해 주세요.'),
        h('div',{class:'nr-note-actions'},h('button',{id:'reportNotesSave',type:'button',class:'btn primary',disabled:busy || !a.can_edit || !draft.dirty || stale || invalid || missingSource,onclick:function () { mutate('save'); }},'문안 저장'),
          h('button',{id:'reportNotesApprove',type:'button',class:'btn',disabled:busy || !a.can_approve || draft.dirty || stale || a.state !== 'draft',onclick:function () { mutate('approve'); }},'검토 후 공유 승인'),
          h('button',{type:'button',class:'btn',disabled:busy,onclick:function () { if (!current() || savingNotes[key]) return; delete drafts[key]; renderDetail(report,mark,ctx); }},'입력 초안 버리기')),
        h('div',{id:'reportNotesCandidate'},sharedContent(report,draft.document,true)),
        notesHistory(a));
    }
    function makePaper(report,options) {
      options = options || {};
      var kind = Object.prototype.hasOwnProperty.call(LAYOUTS,options.layout) ? options.layout : 'a';
      var p = report.payload || {}, period = p.period || {}, scope = report.scope || {}, detail = p.details || {}, comparison = detail.comparison || {};
      var extra = enrichment(report), shared = approvedShared(report), printing = options.print === true;
      var available = p.format_version === 2 && Array.isArray(detail.daily);
      function meta() {
        return h('section',{class:'nr-paper-meta'},h('h3',null,'보고서 기준'),
          h('p',null,env.periodText(period.start,period.end) + ' · ' + (period.kind === 'monthly' ? '월간' : '주간')),
          h('p',{class:'nr-account-scope'},scope.kind === 'company' && detail.status === 'legacy_unavailable' ? '이전 판 · 포함 계정 상세 미보관' : scope.kind === 'company' ? '업체 전체 합산 · ' + env.num((scope.accounts || []).length) + '개 계정 · ' +
            (scope.accounts || []).map(function (account) { return (account.account_name || '계정') + ' (' + (account.ad_account_no || '번호 미확인') + ')'; }).join(', ') :
            (scope.account_name || '계정 이름 미확인') + ' · 광고 계정 ID ' + (scope.ad_account_no || '미확인')),
          h('p',{class:'report-meta'},'담당 ' + (report.owner && report.owner.name || '미확인') + ' · 저장된 ' + env.num(report.revision_no) + '판'),
          h('p',{class:'hint'},'수치판 생성 ' + env.datedTime(report.generated_at)),
          h('p',{class:'nr-compare-note'},'비교 기간: ' + (comparison.period ? env.periodText(comparison.period.start,comparison.period.end) : '자료 미보관') + ' · 전주/전월 비교이며 이전 판 정정과 다릅니다. 비율 차이는 %p로 표시합니다.'));
      }
      function brief() {
        return h('section',{class:'nr-brief'},h('h3',null,'이번 기간, 세 줄로 보기'),
          (detail.briefing || []).length ? h('ol',null,detail.briefing.map(function (line) { return h('li',null,line); })) :
            h('p',null,'검증된 상세 자료가 부족해 요약을 작성하지 않았습니다.'),h('p',{class:'hint'},'저장된 숫자로 만든 요약입니다. 성과 원인이나 향후 매출을 추정하지 않습니다.'));
      }
      function kpis() { return h('dl',{class:'nr-kpis'},['spend','conversion_value','conversions','roas','cpa','cvr'].map(function (key) { return metricCard(report,key); })); }
      function comparisonSection(open) {
        var content = Array.isArray(extra.metrics) ? comparisonTable(extra.metrics) : h('p',{class:'hint'},'이 저장판의 추가 지표·비교 범위는 미보관입니다. 현재 자료로 채우지 않습니다.');
        return open ? h('section',{class:'nr-comparison'},h('h3',null,'17개 지표 · 현재와 직전 기간'),content) :
          h('details',{class:'nr-comparison',open:printing},h('summary',null,'17개 지표 · 현재와 직전 기간'),content);
      }
      function chart() {
        return h('section',{class:'nr-chart-panel',id:printing ? null : 'reportChart'},
          h('h3',null,'일별 성과 흐름 · ' + LABEL[chartMetric]),drawChart(report,chartMetric,printing));
      }
      var notices = [report.status !== 'ready' ? h('div',{class:'nr-notice'},stateLabel(report.status) + '입니다. 아래 숫자는 확인된 자료의 합계이며 전체 기간 성과와 다를 수 있습니다. 미수집 항목은 —로 표시합니다.') : null,
        !available ? h('div',{class:'nr-notice'},'이전 형식으로 저장된 판입니다. 계정별 상세·일별 추이는 보관되지 않았습니다. 이 판의 값을 현재 자료로 바꾸지 않습니다.') : null,
        (extra.period_caveats || []).length ? h('div',{class:'nr-notice'},(extra.period_caveats || []).map(function (line) { return h('p',null,line); })) : null];
      var body;
      if (kind === 'b') {
        body = h('div',{class:'nr-analysis-grid'},h('aside',{class:'nr-analysis-meta'},meta(),qualityCards(report)),
          h('div',{class:'nr-analysis-main'},notices,comparisonSection(true),chart(),brief(),feedback(report),sharedContent(report,shared,false),targetSection(report,shared)));
      } else if (kind === 'c') {
        body = [meta(),notices,qualityCards(report),kpis(),h('div',{class:'nr-strategy-grid'},h('div',null,brief(),feedback(report)),
          h('aside',{class:'nr-strategy-plan'},sharedContent(report,shared,false),targetSection(report,shared))),chart(),comparisonSection(false)];
      } else {
        body = [meta(),notices,qualityCards(report),brief(),kpis(),h('div',{class:'nr-a-review-grid'},chart(),sharedContent(report,shared,false)),
          feedback(report),targetSection(report,shared),comparisonSection(false)];
      }
      var paper = h('article',{class:'nr-report nr-report-paper nr-layout-' + kind,'data-layout':kind,'data-report-id':String(report.report_id),
        'data-revision-fingerprint':report.revision_fingerprint,'data-account-key':scope.account_key},
        h('header',{class:'nr-report-header'},h('div',null,h('p',{class:'nr-eyebrow'},'META I&C · NAVER ADS REPORT'),
          h('h2',{class:'nr-paper-title',id:printing ? null : 'reportDetailTitle'},report.company_name + ' ' + (period.kind === 'monthly' ? '월간' : '주간') + ' 보고서'),
          h('p',{class:'nr-subtitle'},env.periodText(period.start,period.end))),h('span',{class:'nr-layout-label'},LAYOUTS[kind])),
        body,h('p',{class:'nr-public-caveat'},'전환은 광고 플랫폼의 이벤트 수이며 주문·구매자 수와 다를 수 있습니다. 광고 전환가치는 실제 주문·결제 매출과 별도입니다. ROAS·전환율·전환당 비용은 기본·전환이 함께 확인된 범위로 계산합니다.'),
        h('details',{class:'nr-day-table',open:printing},h('summary',null,'일별 숫자 보기'),dailyTable(detail.daily || [])),contributions(report),
        h('section',{class:'nr-public-quality'},h('h3',null,'집계 범위 · 누락 확인'),h('p',{class:'report-meta'},'기본 지표 ' + env.num((p.coverage || {}).basic_complete_account_days) + '/' + env.num((p.coverage || {}).expected_account_days) +
          ' 계정×일 · 전환 지표 ' + env.num((p.coverage || {}).conversion_complete_account_days) + '/' + env.num((p.coverage || {}).expected_account_days) + ' 계정×일'),
          h('p',{class:'hint'},'누락된 일자나 지표는 0이 아닙니다. 부분 집계 PDF에도 미확인 범위를 표시합니다.'),missingDetails(p)),
        h('footer',{class:'nr-report-footer'},'META I&C · 네이버 광고 성과 보고서',h('span',null,'PDF 저장은 발송이 아닙니다. 사본은 이후 정정되어도 자동 변경되지 않습니다.')));
      if (printing) {
        function expand(node) {
          if ((node.tagName || node.tag || '').toLowerCase() === 'details') node.setAttribute('open','');
          Array.prototype.forEach.call(node.children || [],expand);
        }
        expand(paper);
      }
      return paper;
    }
    function renderDetail(report,mark,ctx) {
      displayedMark = mark; displayedContext = ctx;
      var p = report.payload || {}, scope = report.scope || {}, detail = p.details || {};
      var available = p.format_version === 2 && Array.isArray(detail.daily), chosen = selected;
      function current() { return fresh(mark,ctx) && displayed === report; }
      function switchScope(account) { if (current()) open(chosen,account); }
      put($('reportDetail'),
        h('div',{class:'nr-detail-top'},h('button',{type:'button',class:'link',id:'reportBack',onclick:function () { selected = null; load(filter.page); }},'← 보고서 목록'),
          h('div',{class:'nr-preview-controls'},h('span',{class:'hint'},'현재 로그인 사용자의 공유용 내부 미리보기'),h('button',{id:'reportSharePreview',type:'button',class:'btn sm','aria-pressed':String(sharedView),onclick:function () {
            if (!current()) return; sharedView = !sharedView; renderDetail(report,mark,ctx);
          }},sharedView ? '담당자 편집 보기' : '공유용 검토 보기'))),
        h('section',{class:'card nr-report-controls','aria-label':'보고서 디자인과 PDF 저장'},
          h('div',{class:'nr-layout-tools'},h('span',null,'보고서 디자인'),h('div',{class:'chips','aria-label':'보고서 디자인 선택'},Object.keys(LAYOUTS).map(function (key) {
            return h('button',{type:'button',id:'reportLayout-' + key,class:'chip' + (layout === key ? ' on' : ''),'aria-pressed':String(layout === key),onclick:function () {
              if (!current() || layout === key) return; layout = key; layoutGeneration++;
              try { if (window.sessionStorage) window.sessionStorage.setItem('naver-report-layout',key); } catch (_) {}
              if (window.NaverReportPDF && window.NaverReportPDF.cancelPrint) window.NaverReportPDF.cancelPrint();
              renderDetail(report,mark,ctx);
            }},LAYOUTS[key]);
          }))),h('div',{class:'nr-print-action'},h('button',{type:'button',class:'btn primary',id:'reportPdfDownload',disabled:!available || !exportReady(report),onclick:function () { download(report,this,mark,ctx); }},'PDF 저장'),
            h('p',{class:'hint'},'선택한 디자인의 브라우저 인쇄창에서 PDF로 저장하세요. 저장 완료 여부는 브라우저에서 확인합니다.')),
          h('div',{class:'nr-scope-row'},h('div',{class:'chips','aria-label':'보고서 집계 범위'},
            h('button',{type:'button',class:'chip' + (scope.kind === 'account' ? ' on' : ''),'aria-pressed':String(scope.kind === 'account'),onclick:function () { switchScope(chosen.account_key); }},'이 광고 계정'),
            h('button',{type:'button',class:'chip' + (scope.kind === 'company' ? ' on' : ''),'aria-pressed':String(scope.kind === 'company'),onclick:function () { switchScope('company'); }},'업체 전체 합산')),statusChip(report)),refreshSummary(report)),
        makePaper(report,{layout:layout}),sharedView ? null : h('section',{class:'card nr-internal-review'},annotations(report,mark,ctx),
          h('details',{class:'nr-quality'},h('summary',null,'내부 검토 · 정정 이력 확인'),env.validation(report),env.changes(report),history(report,mark,ctx))));
      renderChart(report,mark,ctx);
    }
    function missingDetails(payload) {
      var rows = Array.isArray(payload.missing) ? payload.missing : null;
      var count = rows ? rows.length : null;
      if (Object.prototype.hasOwnProperty.call(payload,'missing_count')) count = rows && Number.isSafeInteger(payload.missing_count) &&
        payload.missing_count >= rows.length ? payload.missing_count : null;
      var reasons = {day_missing:'해당 날짜 미수집',source_unverified:'원천 확인 전',metrics_incomplete:'일부 지표 미수신'};
      var metrics = {imp:'노출',impressions:'노출',clk:'클릭',clicks:'클릭',spend:'광고비',conversions:'전환',conversion_value:'광고 전환가치'};
      function label(labels,key,fallback) { return typeof key === 'string' && Object.prototype.hasOwnProperty.call(labels,key) ? labels[key] : fallback; }
      var shown = (rows || []).slice(0,100);
      return h('details',{class:'report-missing'},h('summary',null,count === null ? '누락 상세 미보관·미확인' : '누락 ' + env.num(count) + '건 · 날짜·지표 확인'),
        shown.length ? h('ul',null,shown.map(function (item) {
          item = item && typeof item === 'object' ? item : {};
          var day = typeof item.day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(item.day) ? item.day : '날짜 미확인';
          var index = Number.isSafeInteger(item.account_index) && item.account_index > 0 ? env.num(item.account_index) : '미확인';
          var names = Array.isArray(item.metrics) && item.metrics.length ? item.metrics.slice(0,16).map(function (key) { return label(metrics,key,'지표 미확인'); }).join('·') : '지표 미확인';
          return h('li',null,day + ' · 계정 순번 ' + index + ' · ' + label(reasons,item.reason,'사유 미확인') + ' · ' + names);
        })) : h('p',null,count === 0 ? '서버가 보고한 누락이 없습니다. 집계 범위와 생성 상태는 별도로 확인해 주세요.' :
          '이 판의 누락 상세가 보관되지 않았거나 확인되지 않았습니다.'),
        count !== null && count > shown.length ? h('p',{class:'hint'},'앞 ' + env.num(shown.length) + '건 표시 · 전체 누락 ' + env.num(count) + '건') : null);
    }
    function dailyTable(days) {
      return days.length ? h('div',{class:'nr-scroll-table'},h('table',null,h('thead',null,h('tr',null,['날짜','광고비','노출수','클릭수','전환수','광고 전환가치','ROAS','CPA','자료 범위'].map(function (name) { return h('th',null,name); }))),
        h('tbody',null,days.map(function (day) { var cov = day.coverage || {}; return h('tr',null,h('th',{scope:'row'},day.day),['spend','impressions','clicks','conversions','conversion_value','roas','cpa'].map(function (key) { return h('td',{class:'num'},value(day,key)); }),h('td',null,(cov.basic_complete === true ? '기본 완결' : '기본 확인분·미확인') + ' · ' + (cov.conversion_complete === true ? '전환 완결' : '전환 확인분·미확인'))); })))) : h('p',{class:'hint'},'저장된 일별 숫자가 없습니다.');
    }
    function history(report,mark,ctx) {
      var content = h('div'), loaded = false, section;
      section = h('details',{class:'report-history',ontoggle:function () {
        if (!section.open || loaded || !fresh(mark,ctx)) return;
        loaded = true; put(content,h('p',{class:'hint'},'정정 이력을 확인 중입니다…'));
        read();
      }},h('summary',null,'이전 판 · 정정 이력'),content);
      function read(before) {
        if (!fresh(mark,ctx) || displayed !== report) return;
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
      if (!fresh(mark,ctx) || displayed !== report || button.disabled || !exportReady(report)) return;
      var chosenLayout = layout, generation = layoutGeneration;
      function current() { return fresh(mark,ctx) && displayed === report && exportReady(report) && layout === chosenLayout && layoutGeneration === generation; }
      button.disabled = true; button.textContent = '권한·보고서 확인 중…';
      env.api('GET',detailPath(report.report_id,report.scope.account_key)).then(function (verified) {
        if (!current()) return;
        if (!sameEdition(report,verified)) throw new Error('report-changed');
        if (!window.NaverReportPDF || !window.NaverReportPDF.print) throw new Error('pdf-unavailable');
        var paper = makePaper(verified,{layout:chosenLayout,print:true});
        if (!current()) return;
        button.textContent = '인쇄창 준비 중…';
        return window.NaverReportPDF.print(verified,{layout:chosenLayout,paper:paper,isCurrent:current}).then(function (result) {
          if (current() && result && result.started === true) env.toast('인쇄창을 열었습니다. 브라우저에서 PDF로 저장해 주세요.');
        });
      }).catch(function (error) {
        if (!fresh(mark,ctx)) return;
        if (env.denied(error)) { env.purge(error); return; }
        if (!current()) return;
        env.toast(error.message === 'report-changed' ? '보고서 정보가 바뀌었습니다. 새로고침 후 다시 저장해 주세요.' : '인쇄창을 열지 못했습니다. 로그인 상태와 브라우저 인쇄 설정을 확인해 주세요.');
      }).then(function () { if (fresh(mark,ctx) && displayed === report && layoutGeneration === generation) { button.disabled = !exportReady(report); button.textContent = 'PDF 저장'; } });
    }
    return {load:load,makePaper:makePaper,company:function (pid) { filter.pid = pid; filter.q = ''; filter.page = 0; selected = null; displayed = null; },
      notesCapability:notesCapability,hasUnsaved:dirty,reset:function () { epoch++; layoutGeneration++; if (window.NaverReportPDF && window.NaverReportPDF.cancelPrint) window.NaverReportPDF.cancelPrint(); clearTimeout(searchTimer); selected = null; displayed = null; displayedMark = null; displayedContext = null; lastList = null; listReady = false; listContext = null; drafts = {}; savingNotes = {}; sharedView = false; filter = {kind:'weekly',anchor:'',requestAnchor:'',q:'',page:0,pid:null}; anchors = {}; if (initialized) controls(); put($('reportDetail')); put($('reportUnlinked')); }};
  }
  window.NaverReports = {create:create,model:{query:query,changeText:changeText,sameEdition:sameEdition,metric:metric}};
}());
