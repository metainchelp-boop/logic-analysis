/* 영업 전용 조회 화면. 전달받은 GET 함수만 사용하며 관리 화면의 응답·초안·캐시를 재사용하지 않는다. */
(function (window) {
  'use strict';
  var current = null;
  var METRICS = [
    ['impressions', '노출', 'count'], ['clicks', '클릭', 'count'], ['cost', '광고비', 'money'],
    ['conversions', '전환', 'conversion'], ['revenue', '광고 전환가치', 'money'], ['ctr', '클릭률', 'percent'],
    ['cpc', '평균 클릭비용', 'money'], ['cvr', '전환율', 'percent'], ['cpa', '전환당 비용', 'money'], ['roas', 'ROAS', 'percent']
  ];
  function object(value) { return !!value && typeof value === 'object' && !Array.isArray(value); }
  function text(value, fallback) { return typeof value === 'string' && value ? value : (fallback || '미확인'); }
  function positive(value) { return Number.isSafeInteger(value) && value > 0; }
  function amount(value, unit) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '미확인';
    return value.toLocaleString('ko-KR', {maximumFractionDigits: unit === 'percent' ? 2 : unit === 'money' ? 0 : 2}) +
      (unit === 'money' ? '원' : unit === 'percent' ? '%' : unit === 'conversion' ? '건' : '회');
  }
  function node(tag, cls, value) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  function add(parent) {
    Array.prototype.slice.call(arguments, 1).forEach(function (child) { if (child) parent.appendChild(child); });
    return parent;
  }
  function empty(parent) { parent.replaceChildren(); }
  function button(label, fn, cls) {
    var el = node('button', 'ns-button' + (cls ? ' ' + cls : ''), label);
    el.type = 'button'; el.addEventListener('click', fn); return el;
  }
  function dateText(value) {
    if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return '미확인';
    return new Date(value).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'});
  }
  function periodText(period) {
    if (!object(period) || typeof period.start !== 'string' || typeof period.end !== 'string') return '기간 미확인';
    return (period.kind === 'monthly' ? '월간' : '주간') + ' · ' + period.start + ' ~ ' + period.end;
  }
  function connection(value) {
    var labels = {linked: '계정 연결됨', connected: '계정 연결됨', matched: '계정 연결됨',
      pending: '계정 연결 대기', unlinked: '계정 연결 대기', not_linked: '계정 연결 대기'};
    return Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : '연결 상태 미확인';
  }
  function status(value) {
    var labels = {approved: '승인 공유본 있음', ready: '성과 집계됨', complete: '성과 집계됨',
      partial: '일부 자료 확인', collecting: '자료 집계 중', pending: '자료 확인 대기',
      conversion_unconfirmed: '기본 자료 완결 · 전환 미확인', basic_incomplete: '기본 자료 부분 집계', unknown: '자료 미확인',
      not_generated: '보고서 생성 대기', unavailable: '자료 미확인', unapproved: '공유 승인 대기'};
    return Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : '상태 확인 필요';
  }
  function metrics(values, compact) {
    var grid = node('dl', 'ns-metrics' + (compact ? ' ns-metrics-compact' : ''));
    METRICS.slice(0, compact ? 5 : METRICS.length).forEach(function (metric) {
      var value = object(values) ? values[metric[0]] : null;
      var cell = node('div', 'ns-metric');
      add(cell, node('dt', '', metric[1]), node('dd', '', amount(value, metric[2]))); add(grid, cell);
    });
    return grid;
  }
  function companyValid(item) {
    return object(item) && positive(item.possibility_id) && typeof item.company_name === 'string' &&
      item.stage === '진행중' && Array.isArray(item.accounts) && item.accounts.length <= 100 && item.accounts.every(function (account) {
        return object(account) && typeof account.account_key === 'string' && /^[0-9a-f]{64}$/.test(account.account_key);
      });
  }
  function invalid() { var error = new Error('sales-response-invalid'); error.code = 'sales-response-invalid'; return error; }
  function live(state, generation) { return current === state && state.generation === generation; }
  function cancelPrint(state) {
    if (state.printCleanup) state.printCleanup();
  }
  function clearRequest(state) {
    if (state.controller) state.controller.abort();
    state.controller = null;
  }
  function reset() {
    if (!current) return;
    var state = current; current = null; state.generation++;
    clearRequest(state); cancelPrint(state); empty(state.root);
  }
  function request(state, path, query, render) {
    clearRequest(state); cancelPrint(state);
    var generation = ++state.generation;
    state.controller = new AbortController();
    empty(state.body); state.status.textContent = '현재 조회 권한과 자료를 확인하고 있습니다…';
    state.status.className = 'ns-status'; state.body.setAttribute('aria-busy', 'true');
    return Promise.resolve().then(function () {
      if (!live(state, generation)) return null;
      return state.api(path, query, {signal: state.controller.signal});
    }).then(function (data) {
      if (!live(state, generation)) return;
      empty(state.body); render(data, generation);
      state.status.textContent = '서버에서 현재 조회 범위를 확인했습니다.';
      state.body.setAttribute('aria-busy', 'false'); state.controller = null;
    }).catch(function (error) {
      if (!live(state, generation)) return;
      clearRequest(state); cancelPrint(state); empty(state.body);
      state.body.setAttribute('aria-busy', 'false');
      if (error && error.status === 404 && path === '/sales/report') {
        state.status.className = 'ns-status';
        state.status.textContent = '승인된 공유 보고서가 아직 없습니다.';
        add(state.body, button('← 업체 목록', function () { if (live(state, generation)) load(state, state.page); }));
        return;
      }
      state.status.className = 'ns-status ns-error';
      state.status.textContent = '현재 권한 또는 자료를 확인하지 못해 기존 화면을 비웠습니다. 다시 확인해 주세요.';
      if (typeof state.onError === 'function') state.onError(error);
    });
  }
  function query(state) {
    var result = {kind: state.kind.value, q: state.search.value.trim(), page: state.page};
    if (state.anchor.value) result.anchor = state.anchor.value;
    return result;
  }
  function reportQuery(state, pid, key) {
    var result = {pid: pid, account_key: key, kind: state.kind.value};
    if (state.anchor.value) result.anchor = state.anchor.value;
    return result;
  }
  function accountCard(state, item, account, generation) {
    var card = node('section', 'ns-account'), title = node('div', 'ns-account-head');
    add(title, node('h3', '', text(account.account_name, '광고 계정')),
      node('span', 'ns-tag', status(account.status)));
    add(card, title, node('p', 'ns-meta', '광고 계정 ' + text(account.ad_account_no)), metrics(account.metrics, true));
    if (positive(account.report_id)) {
      add(card, button('공유 보고서 확인', function () {
        if (live(state, generation)) openReport(state, item.possibility_id, account.account_key);
      }));
    } else add(card, node('p', 'ns-muted', '현재 기간에 조회 가능한 승인 공유 보고서가 없습니다.'));
    return card;
  }
  function companyCard(state, item, generation, detail) {
    var card = node('article', 'ns-company'), head = node('div', 'ns-company-head'), identity = node('div');
    add(identity, node('h2', '', item.company_name), node('p', 'ns-meta', '진행중 · ' + connection(item.connection_status)));
    add(head, identity);
    if (!detail) add(head, button('진행 상태 보기', function () {
      if (live(state, generation)) openDetail(state, item.possibility_id);
    }));
    add(card, head);
    if (!item.accounts.length) add(card, node('p', 'ns-empty', '계정 연결 대기 · 연결된 계정이 없어 성과 수치를 표시하지 않았습니다.'));
    else item.accounts.forEach(function (account) { add(card, accountCard(state, item, account, generation)); });
    return card;
  }
  function sourceLine(data) {
    return node('p', 'ns-meta', periodText(data.period) + ' · 자료 기준 ' + dateText(data.source_as_of));
  }
  function load(state, page) {
    state.page = page;
    return request(state, '/sales/clients', query(state), function (data, generation) {
      if (!object(data) || !Array.isArray(data.items) || data.items.length > 100 || !data.items.every(companyValid) ||
          !Number.isSafeInteger(data.total) || data.total < data.items.length || !positive(data.page) ||
          data.page !== page || data.page_size !== 100) throw invalid();
      if (object(data.period) && /^\d{4}-\d{2}-\d{2}$/.test(data.period.start)) state.anchor.value = data.period.start;
      add(state.body, sourceLine(data), node('p', 'ns-count', '본인 계약 진행중 광고주 ' + data.total.toLocaleString('ko-KR') + '곳 · 업체별 계정을 각각 표시합니다.'));
      if (!data.items.length) add(state.body, node('p', 'ns-empty', '현재 조건에서 조회 가능한 광고주가 없습니다.'));
      data.items.forEach(function (item) { add(state.body, companyCard(state, item, generation, false)); });
      var pages = Math.max(1, Math.ceil(data.total / 100)), nav = node('nav', 'ns-pages');
      nav.setAttribute('aria-label', '광고주 페이지');
      var prev = button('이전', function () { if (live(state, generation)) load(state, page - 1); });
      var next = button('다음', function () { if (live(state, generation)) load(state, page + 1); });
      prev.disabled = page <= 1; next.disabled = page >= pages;
      add(nav, prev, node('span', '', page + ' / ' + pages + ' 페이지 · 100곳씩 표시'), next); add(state.body, nav);
    });
  }
  function openDetail(state, pid) {
    var params = {pid: pid, kind: state.kind.value};
    if (state.anchor.value) params.anchor = state.anchor.value;
    request(state, '/sales/detail', params, function (data, generation) {
      if (!companyValid(data) || data.possibility_id !== pid) throw invalid();
      add(state.body, button('← 업체 목록', function () { if (live(state, generation)) load(state, state.page); }),
        sourceLine(data), companyCard(state, data, generation, true));
    });
  }
  function reportValid(data, params) {
    return object(data) && typeof data.company_name === 'string' && typeof data.account_name === 'string' &&
      data.possibility_id === params.pid && data.account_key === params.account_key && positive(data.approval_version) &&
      object(data.period) && data.period.kind === params.kind &&
      /^\d{4}-\d{2}-\d{2}$/.test(data.period.start) && /^\d{4}-\d{2}-\d{2}$/.test(data.period.end) &&
      object(data.metrics) && object(data.comment);
  }
  function reportPaper(data) {
    var paper = node('article', 'ns-report');
    add(paper, node('p', 'ns-eyebrow', '승인 공유 보고서'), node('h2', '', data.company_name),
      node('p', 'ns-meta', text(data.account_name, '광고 계정') + ' · ' + periodText(data.period)), metrics(data.metrics, false));
    // 허용한 공유 문안만 선택한다. 응답에 다른 필드가 생겨도 이 화면에 자동으로 추가하지 않는다.
    var comment = data.comment;
    add(paper, node('h3', '', '성과 피드백'), node('p', 'ns-comment', text(comment.shared_comment, '승인된 코멘트가 없습니다.')),
      node('h3', '', '앞으로의 운영 계획'), node('p', 'ns-comment', text(comment.next_plan, '승인된 계획이 없습니다.')));
    if (typeof comment.plan_due === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(comment.plan_due))
      add(paper, node('p', 'ns-meta', '계획 기한 · ' + comment.plan_due));
    if (object(comment.targets)) {
      var labels = {spend_per_day: ['일평균 광고비', 'money'], cpa: ['목표 CPA', 'money'], roas: ['목표 ROAS', 'percent']};
      var targets = node('dl', 'ns-metrics ns-targets');
      Object.keys(labels).forEach(function (key) {
        var value = comment.targets[key];
        if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return;
        add(targets, add(node('div', 'ns-metric'), node('dt', '', labels[key][0]), node('dd', '', amount(value, labels[key][1]))));
      });
      if (targets.childNodes.length) add(paper, node('h3', '', '승인된 목표'), targets);
    }
    add(paper, node('p', 'ns-footnote', '광고 전환가치는 플랫폼 전환금액이며 실제 주문·결제 매출과 별도입니다. 미확인 자료를 0으로 대체하지 않았습니다. 계획 기록은 업무 완료를 뜻하지 않습니다.'));
    return paper;
  }
  function printReport(state, params) {
    // 출력 직전에도 동일 전용 API에서 현재 권한·계정 연결·공유 승인을 다시 확인한다.
    request(state, '/sales/report', params, function (data, generation) {
      if (!reportValid(data, params)) throw invalid();
      renderReport(state, data, params, generation);
      var wrapper = node('div', 'ns-print-root'), oldTitle = document.title;
      add(wrapper, reportPaper(data)); document.body.appendChild(wrapper);
      var filename = data.company_name.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, '_').slice(0, 100);
      document.title = filename + '_' + (data.period.kind === 'monthly' ? '월간' : '주간') + '보고서_' + data.period.start + '_' + data.period.end;
      document.body.classList.add('ns-printing');
      var media = window.matchMedia ? window.matchMedia('print') : null, cleaned = false;
      function cleanup() {
        if (cleaned) return;
        cleaned = true;
        window.removeEventListener('afterprint', cleanup);
        if (media && media.removeEventListener) media.removeEventListener('change', mediaChanged);
        wrapper.remove(); document.body.classList.remove('ns-printing'); document.title = oldTitle;
        if (state.printCleanup === cleanup) state.printCleanup = null;
      }
      function mediaChanged(event) { if (!event.matches) cleanup(); }
      state.printCleanup = cleanup;
      window.addEventListener('afterprint', cleanup);
      if (media && media.addEventListener) media.addEventListener('change', mediaChanged);
      if (!live(state, generation)) { cleanup(); return; }
      try { window.print(); } catch (error) { cleanup(); throw error; }
    });
  }
  function renderReport(state, data, params, generation) {
    add(state.body, add(node('div', 'ns-report-actions'),
      button('← 업체 목록', function () { if (live(state, generation)) load(state, state.page); }),
      button('승인 보고서 PDF 저장', function () { if (live(state, generation)) printReport(state, params); }, 'ns-primary')),
      node('p', 'ns-meta', '출력 직전에 현재 공유 승인을 다시 확인합니다. 브라우저 인쇄창에서 PDF로 저장해 주세요.'), reportPaper(data));
  }
  function openReport(state, pid, key) {
    var params = reportQuery(state, pid, key);
    request(state, '/sales/report', params, function (data, generation) {
      if (!reportValid(data, params)) throw invalid(); renderReport(state, data, params, generation);
    });
  }
  function mount(options) {
    reset();
    if (!options || !options.root || typeof options.api !== 'function') throw new Error('sales-ui-options');
    var state = {root: options.root, api: options.api, me: options.me, onError: options.onError, page: 1, generation: 0};
    current = state;
    var shell = node('section', 'ns-sales'), heading = node('header', 'ns-heading');
    add(heading, add(node('div'), node('p', 'ns-eyebrow', '영업 전용'), node('h1', '', '내 계약 광고주'),
      node('p', 'ns-lead', '현재 진행중인 본인 계약 광고주의 진행 상태와 성과, 승인된 공유 보고서를 확인합니다.')),
      node('span', 'ns-readonly', '보기 전용'));
    var form = node('form', 'ns-filters');
    state.kind = node('select'); state.kind.setAttribute('aria-label', '보고서 기간');
    [['weekly', '주간'], ['monthly', '월간']].forEach(function (pair) {
      var option = node('option', '', pair[1]); option.value = pair[0]; add(state.kind, option);
    });
    state.anchor = node('input'); state.anchor.type = 'date'; state.anchor.setAttribute('aria-label', '보고서 기준일');
    state.search = node('input'); state.search.type = 'search'; state.search.maxLength = 200;
    state.search.placeholder = '본인 계약 업체 검색'; state.search.setAttribute('aria-label', '본인 계약 업체 검색');
    var submit = button('조회', function () {}); submit.type = 'submit';
    add(form, add(node('label'), node('span', '', '기간'), state.kind),
      add(node('label'), node('span', '', '기준일'), state.anchor),
      add(node('label', 'ns-search'), node('span', '', '업체 검색'), state.search), submit);
    form.addEventListener('submit', function (event) { event.preventDefault(); if (current === state) load(state, 1); });
    state.kind.addEventListener('change', function () { state.anchor.value = ''; if (current === state) load(state, 1); });
    state.status = node('p', 'ns-status'); state.status.setAttribute('role', 'status'); state.status.setAttribute('aria-live', 'polite');
    state.body = node('div', 'ns-body');
    add(shell, heading, form, state.status, state.body); empty(state.root); add(state.root, shell);
    return load(state, 1);
  }
  window.NaverSalesUI = {mount: mount, reset: reset};
})(window);
