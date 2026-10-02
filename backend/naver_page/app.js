/* 네이버 관제 화면(S13) — 엔진 화면 API(/api/naver-auto · S11)를 ③ 중계(S12)로 부른다.
 *
 * 지키는 것(설계 v1.8 S13 · 시험이 고정)
 * - 색·「확인 필요」·숫자·누를 수 있는 단추는 **서버가 준 값만** 그린다. 이 파일은 판정하지 않는다.
 * - 전산이 준 sso 는 받자마자 주소창에서 지우고(다른 요청보다 먼저) 한 번만 쓴다. 저장하지 않는다.
 * - 자체 토큰은 sessionStorage 의 「naverWatch.session」 — ③ 광고센터 로그인 토큰(브라우저 오래 두는 저장소의 「token」)과
 *   다른 이름·다른 곳.
 *   ③ 토큰은 읽지도 보내지도 않는다. 토큰(1시간)이 끝나기 10분 전에 /session/refresh(1분마다 살핌 · 토큰 끝 시각에서 센다 ·
 *   새로 고침해도 어긋나지 않게). 1시간 넘게 손대지 않으면 이 창의 로그인을 끝낸다(여럿이 쓰는 PC).
 * - 화면에 쓰는 글자는 모두 textContent 로(HTML 로 끼워 넣지 않는다) · 바깥 주소 0 · 이동은 /naver/ 안의 정해진 주소만.
 */
(function () {
  'use strict';

  var API = '/api/naver-auto';
  var KEY = 'naverWatch.session';
  var TICK_MS = 60 * 1000;                  // 1분마다 세션을 살핀다
  var REFRESH_AHEAD_MS = 10 * 60 * 1000;    // 토큰이 끝나기 10분 전에 갱신 — 페이지를 연 때가 아니라 토큰 끝 시각에서
  var IDLE_MS = 60 * 60 * 1000;             // 1시간 넘게 손대지 않으면 이 창의 로그인을 끝낸다(서버 12시간과 별도)
  var END_WARN_MS = 15 * 60 * 1000;         // 로그인 뒤 12시간이 끝나기 15분 전에 한 번 알린다
  var SCREEN = /^\/naver\/(?:(dashboard|issues|system|unlinked|ended|links|settings|automation|reports|transfers)|clients\/([1-9][0-9]{0,17}))?$/;

  var state = {
    session: null, me: null, selection: 'all', filter: 'need', q: '', board: null, links: null, ended: null,
    client: null, clientId: null, ctab: 'now', spane: 'th', settings: null, health: null, bell: null,
    linksOpen: false, endedOpen: false, doneOpen: false, gen: 0, timer: null, focus: null,
    lastInput: Date.now(), refreshing: false, retryAt: 0, retryN: 0, warned: false, bellGen: 0,
    filterFromRoute: false, spaneFromRoute: false, busy: {}, loadedDay: null, lastFocus: null,
    inventory: null, inventoryGen: 0, inventoryMapping: 'all', inventoryWorkflow: 'all', inventoryQ: '', inventoryView: 'current',
    dashboard: null, reports: null, reportsGen: 0, linksGen: 0
  };

  // ── 작은 도구 ─────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
    el.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
  }
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') el.className = v;
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2), v);
        else if (k === 'style') throw new Error('style');
        else el.setAttribute(k, v === true ? '' : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function put(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    for (var i = 1; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function num(n) { return typeof n === 'number' && isFinite(n) ? n.toLocaleString('ko-KR') : '—'; }
  function won(n) { return typeof n === 'number' && isFinite(n) ? Math.trunc(n).toLocaleString('ko-KR') + '원' : '—'; }
  function hm(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return '';
    return d.toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function md(day) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day || '');
    return m ? (+m[2]) + '/' + (+m[3]) : '';
  }
  function mdhm(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return '';
    var p = d.toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric' });
    return p.replace(/\.\s*/g, '/').replace(/\/$/, '') + ' ' + hm(iso);
  }
  function datedTime(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return '확인 시각 없음';
    return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }) + ' ' + hm(iso) + ' KST';
  }
  function periodText(start, end) {
    return /^\d{4}-\d{2}-\d{2}$/.test(start || '') && /^\d{4}-\d{2}-\d{2}$/.test(end || '') ?
      (start === end ? start : start + ' ~ ' + end) : '실적 기간 미확인';
  }
  /* 한국 날짜(YYYY-MM-DD) — 브라우저 시계로 「날짜가 바뀌었나」만 본다(예외 기간은 서버의 오늘로 센다) */
  function kstDay() {
    try { return new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }); } catch (e) { return null; }
  }
  /* 같은 일을 두 번 보내지 않게 — 누른 단추를 잠그고 끝나면 푼다 */
  function once(key, btn, run) {
    if (state.busy[key]) return;
    state.busy[key] = true;
    if (btn) btn.disabled = true;
    var done = function () { delete state.busy[key]; if (btn) btn.disabled = false; };
    run().then(done, done);
  }
  function toast(t) {
    var el = $('toast');
    el.textContent = t;
    el.classList.add('on');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.classList.remove('on'); }, 3200);
  }

  // ── 서버 글자 → 화면 글자(뜻을 바꾸지 않고 옮긴다) ─────────────────────
  var STAGE = { '진행중': '진행중', '전략관리': '전략 관리', '사후관리': '사후 관리', '홀딩중': '홀딩중',
                '재계약진행중': '재계약 진행중', '환불중': '환불중', '계약만료': '계약 만료' };
  var COLOR_TEXT = { red: '긴급', yellow: '주의', green: '정상', white: '점검 불가' };
  var WHITE_TEXT = {
    not_checked: '오늘 점검 안 됨', partial: '일부만 읽힘', key_rejected: '읽기 거절 · 이관 남음',
    link_broken: '🔌 이관 빠짐', not_eligible: '점검 대상 아님', link_missing: '오늘 이관 목록에 없음',
    data_late: '네이버 자료 늦음', system_gap: '우리 쪽 자료 문제', pending: '점검 전', no_link: '이어진 계정 없음',
    unreadable: '판정 못 함'
  };
  var LINK = {
    listed: ['p-green', '이관됨'], missing: ['p-amber', '오늘 목록에 없음'], broken: ['p-red', '🔌 이관 빠짐'],
    not_linked: ['p-gray', '이관 안 됨'], none: ['p-gray', '이어진 계정 없음'], pending: ['p-gray', '짝 맞추기 전']
  };
  var BLOCKED = { 'org-stale': '🙈 조직 자료가 낡아 예외는 잠시 막힘', 'actor-too-low': '🙈 긴급 예외는 대표만',
                  'exception-active': '🙈 끝난 예외 — 다음 아침 점검 뒤 다시 줄 수 있음' };
  var STATE = { 'new': '🆕 새로', ack: '👀 확인 중', resolved: '✅ 해결', auto_resolved: '🔁 저절로 풀림',
                exception: '🙈 예외', closed_unlinked: '짝이 사라져 닫힘' };
  var REL = { main: null, sub: '서브', prev: '이전 담당', team: null, all: null };
  var CAUSE = {
    bizmoney_low: '비즈머니가 곧 바닥납니다', bizmoney_empty: '비즈머니가 0원입니다',
    budget_lock: '예산 잠금으로 광고가 멈췄습니다', refund_lock: '환불 잠금이 걸려 있습니다',
    active_no_impressions: '켜져 있는데 광고가 안 나갑니다', spend_up: '광고비가 갑자기 늘었습니다',
    spend_down: '광고비가 갑자기 줄었습니다', spend_after_contract: '계약 단계와 광고비가 맞지 않습니다',
    running_zero_spend: '진행중인데 광고비가 0원입니다', period_ending: '캠페인 기간이 곧 끝납니다',
    key_rejected: '네이버가 읽기를 거절했습니다 (이관은 남아 있음)', link_broken: '🔌 이관이 빠졌습니다'
  };
  function cause(code) { return CAUSE[code] || ('점검 항목 (' + code + ')'); }
  function fact(i) {
    var f = i.facts || {};
    switch (i.code) {
      case 'bizmoney_low': return typeof f.days_left === 'number' ? '최근 7일 하루 평균 광고비로 약 ' + f.days_left + '일 남음' : '';
      case 'bizmoney_empty': return '켜진 캠페인이 있는데 잔액이 없습니다';
      case 'active_no_impressions':
        return '켜진 캠페인 ' + num(f.had_impressions) + '개 중 ' + num(f.stopped) + '개가 어제 노출 0' +
          ((f.hints || []).indexOf('shared-budget-lock') >= 0 ? ' · 공유 예산 잠김' : '') +
          ((f.hints || []).indexOf('bizmoney') >= 0 ? ' · 비즈머니 부족도 함께' : '');
      case 'spend_up': case 'spend_down': return '어제 ' + won(f.yesterday) + ' · 같은 요일 평균 ' + won(f.baseline);
      case 'spend_after_contract': return '전산 단계 「' + (STAGE[f.stage] || f.stage || '') + '」인데 어제 광고비 ' + won(f.yesterday);
      case 'running_zero_spend': return typeof f.days === 'number' ? '최근 ' + f.days + '일 광고비 합계 0원' : '';
      case 'period_ending': return typeof f.days_left === 'number' ? f.days_left + '일 안에 끝남 — 이어 갈지 광고주와 확인' : '';
      case 'key_rejected': return '오늘 점검을 못 했습니다 · 대행 연결 목록에는 있어 이관 빠짐은 아닙니다 · 광고주가 우리 회사 권한을 바꿨을 수 있습니다';
      case 'link_broken':
        return f.reason === 'never-listed' ? '확인한 계정이 대행 연결 목록에 한 번도 없었습니다'
          : '우리 회사 대행 연결 목록에 이 광고주 광고계정이 없습니다 · ' + md(i.first_seen_on) + '부터 · 다시 이관되면 🔁 저절로 풀립니다';
      default: return '';
    }
  }
  var ERR = {
    'source-stale': '현재 원천·업무 단계에 맞는 사유를 아직 확인하지 못했습니다. 목록과 수집 시각을 다시 확인해 주세요',
    'bad-query': '조회 조건이나 페이지가 변경되었습니다. 목록을 새로고침한 뒤 다시 확인해 주세요',
    'stage-changed': '전산 단계가 변경되었습니다. 목록을 새로고침한 뒤 다시 확인해 주세요',
    'report-incomplete': '누락이 남은 보고서는 승인할 수 없습니다. 자료 수집 후 다시 확인해 주세요',
    'verification-read-only': '읽기 전용 검증판에서는 업무 내용을 변경할 수 없습니다',
    'org-stale': '조직 자료가 26시간 넘게 낡아 지금은 할 수 없습니다(확인·해결은 됩니다)',
    'not-visible': '없거나 볼 수 없는 광고주입니다', 'action-not-allowed': '이 광고주에서 할 수 없는 일입니다',
    'not-linkable': '이 계정은 지금 이을 수 없습니다', 'not-eligible': '이 광고주는 지금 미리보기를 할 수 없습니다',
    'preview-unavailable': '미리보기는 준비 중입니다(배포 묶음에서 켭니다)', 'preview-failed': '네이버에서 캠페인 이름을 읽지 못했습니다',
    'ceo-only': '대표님만 할 수 있습니다', 'settings-denied': '담당자는 설정을 보지 않습니다',
    'store-busy': '잠시 뒤 다시 눌러 주세요', 'relay-busy': '잠시 뒤 다시 눌러 주세요', 'engine-unavailable': '관제 엔진에 닿지 않습니다',
    'audit-unavailable': '기록을 남기지 못해 보여 드리지 않았습니다 — 잠시 뒤 다시',
    'not-new': '이미 확인 중이거나 풀린 이슈입니다', 'not-open': '이미 닫힌 이슈입니다',
    'exception-active': '이미 예외 중이거나, 끝난 예외를 다음 아침 점검이 아직 보지 않았습니다',
    'bad-input': '사유에 쓸 수 없는 글자가 있습니다(줄바꿈·특수 서식 글자를 빼고 다시)',
    'org-unavailable': '조직 자료를 아직 받지 못했습니다 — 잠시 뒤 다시', 'store-unavailable': '관제 저장소에 닿지 않습니다 — 잠시 뒤 다시',
    internal: '관제 엔진 오류 — 잠시 뒤 다시', 'engine-timeout': '관제 엔진이 늦게 답합니다 — 잠시 뒤 다시',
    'actor-too-low': '🔴 긴급 예외는 대표만 줄 수 있습니다', 'exception-too-long': '예외 기간이 한도보다 깁니다',
    'exception-in-past': '끝나는 날이 지났습니다', 'note-required': '사유를 적어 주세요', 'bad-body': '입력이 올바르지 않습니다',
    'revoke-refused': '이미 거둔 판단입니다', 'selection-rejected': '고를 수 없는 보기 범위입니다', 'no-change': '바뀐 값이 없습니다',
    'too-many-logins': '들어오기 시도가 많습니다. 잠시 뒤 전산에서 다시 들어와 주세요', network: '네트워크 오류 — 잠시 뒤 다시'
  };
  function errText(e) {
    var j = (e && e.body) || {};
    var code = j.error || '';
    if (code === 'not-verified-link') return '중복·계약·최신 계정 대조를 통과하지 못해 연결하지 않았습니다';
    if (code === 'account-proof-required') return '원본 목록의 광고 계정 ID 숫자가 현재 네이버 계정과 일치해야 확정됩니다';
    if (code === 'collection-unavailable') return '즉시 조회가 준비되지 않았습니다';
    if (code.indexOf('refused-') === 0) code = code.slice(8);
    return ERR[code] || (j.message ? String(j.message) : '처리하지 못했습니다') ;
  }

  // ── 세션 ─────────────────────────────────────────────────────────
  function loadSession() {
    try {
      var s = JSON.parse(sessionStorage.getItem(KEY) || 'null');
      return s && typeof s.token === 'string' ? s : null;
    } catch (e) { return null; }
  }
  function saveSession(j) {
    var s = { token: String(j.token), exp: Date.now() + Math.max(0, +j.expires_in || 0) * 1000,
              ends: j.session_ends_at || null, narrowed: !!j.narrowed };
    state.session = s;
    try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* 저장 못 해도 이 창에서는 쓴다 */ }
  }
  function dropSession() {
    state.session = null;
    try { sessionStorage.removeItem(KEY); } catch (e) { /* 없음 */ }
  }
  function ApiError(status, body) { this.status = status; this.body = body || {}; }
  function api(method, path, body) {
    if (readOnly() && method !== 'GET' && path !== '/session' && path !== '/session/refresh' &&
        !(method === 'POST' && (verifiedLinking() && path === '/links/confirm' || fullCollectionAllowed() && path === '/collection/request')) &&
        !(method === 'POST' && (managementCapability(path, body) || reportCapability(path, body)))) {
      return Promise.reject(new ApiError(403, { error: 'verification-read-only' }));
    }
    var headers = { Accept: 'application/json' };
    if (state.session) headers.Authorization = 'Bearer ' + state.session.token;
    var init = { method: method, headers: headers, credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
                 redirect: 'error' };
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(API + path, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401 && path !== '/session') { lost(); throw new ApiError(401, j); }
        if (!r.ok) throw new ApiError(r.status, j);
        return j;
      });
    }, function () { throw new ApiError(0, { error: 'network' }); });
  }

  // 진입 진단에는 고정 문구만 쓴다. 예외·서버 응답·출처 주소·직원 번호를 그대로 표시하지 않는다.
  var ENTRY_DIAGNOSTICS = {
    'NV-E00': ['🔒', '전산 진입을 확인하지 못했습니다', '이 창을 닫고 전산에서 다시 열어 주세요.'],
    'NV-E01': ['🔒', '로그인 요청을 확인하지 못했습니다', '로그인 요청 형식이 맞지 않습니다. 저장하거나 전달받은 관제 주소로는 들어올 수 없습니다.'],
    'NV-E02': ['🔒', '전산에서 연 출처 정보를 받지 못했습니다', '이 창을 닫고 전산에서 다시 열어 주세요. 반복되면 관리자에게 브라우저의 출처 전달 설정 확인을 요청해 주세요.'],
    'NV-E03': ['🔒', '전산에서 연 창인지 확인하지 못했습니다', '허용된 전산 출처가 아니어서 로그인을 중단했습니다. 전산에 직접 로그인한 뒤 다시 열어 주세요.'],
    'NV-E04': ['🔒', '전산 창과의 연결이 없습니다', '이 창을 연 전산 창과 연결되지 않았습니다. 전산 창을 열어 둔 상태에서 메뉴 단추로 다시 열어 주세요.'],
    'NV-E05': ['🔒', '다른 화면 안에서는 로그인할 수 없습니다', '관제는 별도 창에서 열어야 합니다. 전산 메뉴 단추로 새로 열어 주세요.'],
    'NV-E06': ['⏱', '전산 로그인 응답을 기다리다 종료했습니다', '1분 안에 로그인 응답을 받지 못했습니다. 전산 창이 열려 있고 로그인되어 있는지 확인해 주세요.'],
    'NV-E07': ['🔒', '브라우저의 안전한 로그인 기능을 실행하지 못했습니다', '관리자에게 브라우저의 보안 기능 확인을 요청해 주세요. 보안 설정을 끄지 마세요.'],
    'NV-E08': ['🔒', '로그인 주소를 안전하게 정리하지 못했습니다', '이 창을 닫고 다시 열어 주세요. 주소창 내용은 복사하거나 전달하지 마세요.'],
    'NV-E09': ['🔒', '전산 창에 로그인 요청을 전달하지 못했습니다', '전산 창이 열려 있고 로그인되어 있는지 확인한 뒤 다시 열어 주세요.'],
    'NV-S00': ['🛠', '관제 연결을 완료하지 못했습니다', '잠시 뒤 다시 시도해 주세요. 반복되면 관리자에게 관제 연결 확인을 요청해 주세요.'],
    'NV-S01': ['🛠', '전산 로그인 서버의 응답을 받지 못했습니다', '잠시 뒤 다시 시도해 주세요. 반복되면 관리자에게 전산 로그인 연결 확인을 요청해 주세요.'],
    'NV-S02': ['🛠', '전산 로그인 응답 형식을 확인하지 못했습니다', '관리자에게 전산과 관제 사이의 로그인 연동 확인을 요청해 주세요.'],
    'NV-S03': ['🔒', '전산 로그인을 확인하지 못했습니다', '로그인이 끝났거나 요청이 거절됐을 수 있습니다. 전산에 다시 로그인해 주세요.'],
    'NV-S04': ['🙅', '관제 대상이 아닙니다', '조직 자료에 재직 중으로 있는 직원만 볼 수 있습니다. 전산 조직 정보가 맞는지 관리자에게 확인을 요청해 주세요.'],
    'NV-S05': ['⏳', '잠시 뒤 다시 들어와 주세요', '들어오기 시도가 몰렸습니다. 1분쯤 기다린 뒤 다시 시도해 주세요.'],
    'NV-S06': ['🛠', '관제에 연결할 네트워크를 확인해 주세요', '네트워크 요청을 완료하지 못했습니다. 인터넷 연결을 확인하고, 반복되면 관리자에게 접속 환경 확인을 요청해 주세요.'],
    'NV-S07': ['🛠', '관제 서버에 연결하지 못했습니다', '잠시 뒤 다시 시도해 주세요. 반복되면 관리자에게 관제 서버 연결 확인을 요청해 주세요.'],
    'NV-S08': ['⏳', '관제 서버의 답변이 늦어지고 있습니다', '잠시 뒤 다시 시도해 주세요. 반복되면 관리자에게 관제 서버 상태 확인을 요청해 주세요.'],
    'NV-M01': ['🛠', '직원 권한을 확인할 최신 조직 자료가 없습니다', '조직 자료가 없거나 오래되어 권한 보호를 위해 화면을 열지 않았습니다. 관리자에게 전산 조직 자료 동기화 확인을 요청해 주세요.']
  };
  function entryServerDiagnostic(e) {
    switch (e && e.body && e.body.error) {
      case 'erp-unavailable': return 'NV-S01';
      case 'erp-bad-shape': return 'NV-S02';
      case 'network': return 'NV-S06';
      case 'engine-unavailable': return 'NV-S07';
      case 'engine-timeout': return 'NV-S08';
      case 'org-stale':
      case 'org-unavailable': return 'NV-M01';
      default: return 'NV-S00';
    }
  }
  function blocked(kind, diagnostic) {
    var T = {
      login: ['🔒', '전산에서 들어와 주세요', '네이버 관제는 전산(메타아이앤씨) 「광고 스튜디오 › 네이버 관제(읽기 전용)」 단추로 들어옵니다. 이 주소를 바로 열면 로그인할 수 없습니다.'],
      ended: ['⏱', '다시 들어와 주세요', '로그인이 끝났습니다(로그인 뒤 12시간이 지났거나 서버가 끝냄). 전산 「광고 스튜디오 › 네이버 관제(읽기 전용)」 단추로 다시 들어와 주세요.'],
      idle: ['⏱', '오래 쉬어 로그인을 끝냈습니다 — 다시 들어와 주세요', '1시간 넘게 손대지 않아 이 창의 로그인을 끝냈습니다(여럿이 쓰는 PC 에서 다른 사람이 이어 쓰지 않게). 전산 「광고 스튜디오 › 네이버 관제(읽기 전용)」 단추로 다시 들어와 주세요.'],
      rejected: ['🔒', '전산 로그인을 확인하지 못했습니다', '전산에서 로그아웃됐거나 로그인이 끝났을 수 있습니다. 전산에 다시 로그인한 뒤 「광고 스튜디오 › 네이버 관제(읽기 전용)」 단추로 들어와 주세요.'],
      noscope: ['🙅', '관제 대상이 아닙니다', '조직 자료에 재직 중으로 있는 직원만 볼 수 있습니다. 전산 조직 정보가 맞는지 관리자에게 알려 주세요.'],
      busy: ['⏳', '잠시 뒤 다시 들어와 주세요', '들어오기 시도가 몰렸습니다. 1분쯤 뒤 전산에서 다시 들어와 주세요.'],
      down: ['🛠', '지금 관제에 닿지 않습니다', '전산 확인 또는 관제 엔진이 잠시 멈췄습니다. 잠시 뒤 다시 들어와 주세요.']
    }[kind] || ['🔒', '들어올 수 없습니다', ''];
    if (diagnostic) {
      if (typeof diagnostic !== 'string' || !Object.prototype.hasOwnProperty.call(ENTRY_DIAGNOSTICS, diagnostic)) diagnostic = 'NV-E00';
      T = ENTRY_DIAGNOSTICS[diagnostic];
    }
    $('top').hidden = true;
    $('b-ic').textContent = T[0];
    $('b-t').textContent = T[1];
    $('b-p').textContent = T[2] + (diagnostic ?
      ' 전산 공식 메뉴 「광고 스튜디오 › 네이버 관제(읽기 전용)」에서 다시 들어와 주세요. 진단 코드: ' + diagnostic +
      ' · 계속되면 주소창을 제외한 이 안내만 캡처하여 관리자에게 전달해 주세요.' : '');
    show('blocked');
  }
  function lost(kind) {
    dropSession();
    state.me = null;              // 뒤로 가기가 옛 화면을 다시 그리지 않게
    state.inventory = null;
    state.inventoryGen++;
    state.gen++;
    state.reports = null;
    state.reportsGen++;
    state.links = null;
    state.linksGen++;
    clearInterval(state.timer);
    closeModals();
    closeBell();
    blocked(kind === 'idle' ? 'idle' : 'ended');
  }
  function refresh() {
    if (!state.session || state.refreshing) return Promise.resolve();
    state.refreshing = true;
    return api('POST', '/session/refresh').then(function (j) {
      state.refreshing = false;
      state.retryN = 0;
      state.retryAt = 0;
      saveSession(j);
    }, function (e) {
      state.refreshing = false;
      if (e && e.status === 401) return;   // lost() 가 처리
      state.retryN = Math.min(state.retryN + 1, 5);   // 잠깐 막힘(503 · 네트워크) — 1 · 2 · 4 · 8 · 16분 뒤 다시
      state.retryAt = Date.now() + Math.pow(2, state.retryN - 1) * 60 * 1000;
    });
  }
  /* 1분마다 — 오래 쉬었으면 끝내고 · 토큰이 끝났으면 끝내고 · 끝나기 10분 전이면 갱신 · 12시간 끝 15분 전에 한 번 알림 */
  function tick() {
    var s = state.session;
    if (!s) return;
    var now = Date.now();
    if (now - state.lastInput >= IDLE_MS) { lost('idle'); return; }
    if (now >= s.exp) { lost(); return; }
    if (s.exp - now <= REFRESH_AHEAD_MS && now >= state.retryAt) refresh();
    if (verifiedLinking() && parse(location.pathname).screen === 'watch') loadCollection();
    if (parse(location.pathname).screen === 'dashboard' && state.loadedDay && kstDay() !== state.loadedDay) {
      state.gen++; openDashboard();
    }
    var end = s.ends ? Date.parse(s.ends) : NaN;
    if (!state.warned && isFinite(end) && end > now && end - now <= END_WARN_MS) {
      state.warned = true;
      toast('로그인 뒤 12시간이 ' + hm(s.ends) + '에 끝납니다 — 전산 「광고 스튜디오 › 네이버 관제(읽기 전용)」에서 다시 들어오면 이어집니다');
    }
  }
  function scheduleRefresh() {
    clearInterval(state.timer);
    state.timer = setInterval(tick, TICK_MS);
    tick();   // 새로 고침 · 잠자기 뒤 바로 한 번(토큰이 곧 끝나면 지금 갱신)
  }
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') tick(); });

  // ── 화면 고르기 ────────────────────────────────────────────────────
  var SCREENS = ['loading', 'blocked', 'dashboard', 'watch', 'client', 'automation', 'reports', 'transfers', 'settings'];
  function show(name) {
    SCREENS.forEach(function (s) { var el = $('s-' + s); if (el) el.classList.toggle('on', s === name); });
    var menuKey = { dashboard: '/naver/dashboard', watch: '/naver/', client: '/naver/', automation: '/naver/automation', reports: '/naver/reports',
                    transfers: '/naver/transfers', settings: '/naver/settings' }[name];
    Array.prototype.forEach.call(document.querySelectorAll('.menu button'), function (b) {
      b.classList.toggle('on', b.getAttribute('data-go') === menuKey);
    });
  }
  function parse(path) {
    var m = SCREEN.exec(path);
    if (!m) return { screen: 'watch', focus: null };
    if (m[2]) return { screen: 'client', id: m[2] };
    var n = m[1] || '';
    var screen = { dashboard: 'dashboard', system: 'settings', settings: 'settings', automation: 'automation', reports: 'reports', transfers: 'transfers' }[n] || 'watch';
    return { screen: screen, focus: n || null };
  }
  function go(path) {
    if (!SCREEN.test(path)) path = '/naver/';
    if (path !== location.pathname) history.pushState(null, '', path);
    route();
  }
  window.addEventListener('popstate', function () { if (state.me) route(); });
  function route() {
    var r = parse(location.pathname);
    state.gen++;
    state.links = null;
    put($('linksBody')); $('confirmAuto').hidden = true;
    closeModals();
    if (r.screen === 'client') return openClient(r.id);
    if (r.screen === 'settings') {
      // /naver/system 이 연 「시스템」 칸은 그 주소에서만 — 다른 주소로 다시 오면 처음 칸(사람이 고른 칸은 그대로)
      if (r.focus === 'system') { state.spane = 'sys'; state.spaneFromRoute = true; }
      else if (state.spaneFromRoute) { state.spane = 'th'; state.spaneFromRoute = false; }
      return openSettings();
    }
    if (r.screen === 'automation') { show(r.screen); return; }
    if (r.screen === 'reports') { show('reports'); return loadReports(); }
    if (r.screen === 'transfers') { show('transfers'); return loadInventory(); }
    if (r.screen === 'dashboard') return openDashboard();
    state.focus = r.focus;
    // /naver/unlinked(월요일 알림)가 건 거르기도 그 주소에서만
    if (r.focus === 'unlinked') { state.filter = 'iw_unlinked_numbers'; state.filterFromRoute = true; }
    else if (state.filterFromRoute) { state.filter = 'need'; state.filterFromRoute = false; }
    if (r.focus === 'links') state.linksOpen = true;
    if (r.focus === 'ended') state.endedOpen = true;
    openWatch();
  }

  // ── 위 띠 · 보는 범위 ─────────────────────────────────────────────
  function readOnly() { return !!(state.me && state.me.owner_verification); }
  function verifiedLinking() { return !!(state.me && state.me.verified_linking === true && (state.me.scope === 'ALL' || state.me.scope === 'MINE') && !state.me.narrowed); }
  function fullCollectionAllowed() { return verifiedLinking() && state.me.scope === 'ALL'; }
  function renderTop() {
    var me = state.me;
    $('top').hidden = false;
    $('verificationNotice').hidden = !readOnly();
    $('collectionControls').hidden = !fullCollectionAllowed();
    $('bellAll').hidden = readOnly();
    var kind = { ALL: '대표', TEAM: '팀장', MINE: '담당자' }[me.scope] || '';
    var mine = (me.people || []).filter(function (p) { return p.idx === me.idx; })[0];
    put($('me'), h('b', null, me.name || ''), ' · ' + kind + (me.narrowed ? ' (내 담당만 보기)' : ''),
      mine ? ' · ' + num(mine.account_count) + '계정' : '');
    $('menuSettings').hidden = !(me.scope === 'ALL' || me.scope === 'TEAM');
    var sel = $('scope');
    if (me.scope === 'ALL') {
      var opts = [['all', '전체 이관 계정'], ['me', '내 담당만']];
      if (me.scope === 'ALL') opts.push(['unassigned', '담당 미정']);
      (me.people || []).forEach(function (p) {
        if (p.idx !== me.idx && p.active) opts.push(['person:' + p.idx, (p.name || p.idx) + ' · ' + num(p.account_count) + '계정']);
      });
      put(sel, opts.map(function (o) { return h('option', { value: o[0], selected: o[0] === state.selection }, o[1]); }));
      sel.hidden = false;
    } else {
      sel.hidden = true;
    }
    setBell(me.bell_unread);
  }
  function setBell(n) {
    var c = $('bellN');
    c.hidden = !(n > 0);
    c.textContent = n > 99 ? '99+' : String(n || 0);
    $('bell').setAttribute('aria-label', '나에게 온 알림' + (n > 0 ? ' · 안 읽음 ' + n : ''));
  }

  // 월간 값은 서버 집계를 그대로 표시한다. 부분합·평균·ROAS의 모집단을 화면에서 다시 계산하지 않는다.
  function percent(n) {
    return typeof n === 'number' && isFinite(n) ? n.toLocaleString('ko-KR', { maximumFractionDigits: 2 }) + '%' : '—';
  }
  function dashboardMetric(key, label, value, note, primary) {
    return h('div', { id: 'dashboard-' + key, class: 'dashboard-metric' + (primary ? ' primary' : '') },
      h('span', { class: 'label' }, label), h('span', { class: 'value' }, value), h('span', { class: 'note' }, note));
  }
  function dashboardBreakdown(id, values, labels) {
    put($(id), labels.map(function (pair) {
      return h('div', null, h('span', { class: 'label' }, pair[1]), h('span', { class: 'value' }, num(values && values[pair[0]])));
    }));
  }
  function renderDashboard(data, error) {
    var period = data && data.period || {}, accounts = data && data.accounts || {}, coverage = data && data.coverage || {};
    var advertisers = data && data.advertisers || {}, status = 'loading', message = '저장된 월간 자료를 불러오는 중입니다.';
    var showMetrics = !!(data && data.ready && period.days > 0 && accounts.total > 0 && coverage.complete_accounts > 0);
    var totals = showMetrics ? data.totals || {} : {}, averages = showMetrics ? data.averages || {} : {};
    var ratios = showMetrics ? data.ratios || {} : {};
    if (error) { status = 'error'; message = '월간 자료를 불러오지 못했습니다 — ' + errText(error) + ' 자료 새로고침으로 다시 확인해 주세요.'; }
    else if (data) {
      if (period.days === 0) { status = 'no-period'; message = '이번 달은 아직 집계할 날짜가 없습니다. 어제까지의 실적이 생긴 뒤 표시합니다.'; }
      else if (!data.ready) { status = 'unavailable'; message = '현재 계정 자료를 확인하지 못했습니다. 수신 상태를 확인한 뒤 다시 조회해 주세요.'; }
      else if (accounts.total === 0) { status = 'empty'; message = '현재 조회 범위에 이관 계정이 없습니다.'; }
      else if (!coverage.complete_accounts) {
        if (coverage.retry_accounts > 0 || coverage.limited_accounts > 0) {
          status = 'failed'; message = '월간 성과 수집에 재시도 또는 확인이 필요합니다. 미확인 실적을 0으로 표시하지 않습니다.';
        } else { status = 'collecting'; message = '월간 성과 수집 대기·진행 중입니다. 아직 완결된 계정의 자료가 없습니다.'; }
      } else if (coverage.complete_accounts < accounts.total) {
        status = 'partial'; message = '확인된 계정의 부분 합계입니다. 전체 계정의 성과가 아닙니다.';
      } else { status = 'complete'; message = '현재 조회 범위의 모든 계정에서 월간 기본 실적을 확인했습니다. 전환매출 확인 범위는 별도입니다.'; }
    }
    $('dashboardStatus').setAttribute('data-status', status);
    $('dashboardStatus').textContent = message;
    $('dashboardPeriod').textContent = !data ? '집계 기간 확인 중' : period.days === 0 ? '이번 달 집계 기간 없음 · 한국 시간 기준' :
      (period.start || '—') + ' ~ ' + (period.end || '—') + ' · ' + num(period.days) + '일 · 한국 시간 기준';
    $('dashboardCoverage').textContent = data ? '월간 기본 실적 확인 ' + num(coverage.complete_accounts) + ' / ' + num(accounts.total) +
      '계정 · 대기 ' + num(coverage.pending_accounts) + ' · 부분 수집 ' + num(coverage.partial_accounts) +
      ' · 재시도 ' + num(coverage.retry_accounts) + ' · 확인 필요 ' + num(coverage.limited_accounts) : '확인 범위 —';
    $('dashboardAccounts').textContent = data ? '전산 매칭 ' + num(accounts.matched) + '계정 · 미매칭 ' + num(accounts.unmatched) +
      '계정 · 미분류 ' + num(accounts.unclassified) + '계정 / 전산 광고주 ' + num(advertisers.total) +
      '곳 중 월간 완결 ' + num(advertisers.complete) + '곳 · 미완결 ' + num(advertisers.unknown) + '곳' : '';
    $('dashboardCollected').textContent = data ? '월간 확인 시각 ' + (mdhm(coverage.oldest_collected_at) || '미수집') + ' ~ ' +
      (mdhm(coverage.newest_collected_at) || '미수집') + ' · 계정 목록 ' + (mdhm(data.accounts_at) || '수신 전') +
      ' · 전산 목록 ' + (mdhm(data.catalog_at) || '수신 전') : '';
    var totalNote = '월간 확인 ' + num(coverage.complete_accounts) + ' / ' + num(accounts.total) + '계정';
    var advertiserNote = '모든 계정이 완결된 전산 광고주 ' + num(advertisers.complete) + '곳 기준';
    put($('dashboardMetrics'),
      dashboardMetric('spend', '월 누적 광고비', won(totals.spend), totalNote, true),
      dashboardMetric('daily-spend', '일평균 광고비', won(averages.daily_spend), '확인된 기간 광고비 ÷ 집계 일수'),
      dashboardMetric('advertiser-spend', '광고주당 일평균 광고비', won(averages.advertiser_daily_spend), advertiserNote),
      dashboardMetric('impressions', '월 누적 노출', num(totals.impressions), '완결 광고주당 평균 ' + num(averages.advertiser_impressions) + '회'),
      dashboardMetric('clicks', '월 누적 클릭', num(totals.clicks), '완결 광고주당 평균 ' + num(averages.advertiser_clicks) + '회'),
      dashboardMetric('ctr', '클릭률 (CTR)', percent(ratios.ctr), '동일 확인 계정의 클릭 ÷ 노출'),
      dashboardMetric('cpc', '클릭당 광고비 (CPC)', won(ratios.cpc), '동일 확인 계정의 광고비 ÷ 클릭'),
      dashboardMetric('roas', '광고비 대비 전환매출 (ROAS)', percent(ratios.roas), '전환매출까지 확인된 계정만'));
    $('dashboardRatioNote').textContent = showMetrics ? 'ROAS 확인 ' + num(ratios.roas_accounts) + '계정 · 같은 계정의 광고비 ' +
      won(ratios.roas_spend) + ' · 전환매출 ' + won(ratios.roas_conversion_value) +
      '. 전환 추적 여부가 불명인 0매출은 제외합니다. 광고주 평균은 미매칭 계정을 제외한 월간 완결 광고주 기준입니다.' :
      '미수집·미확인 지표와 분모가 없는 비율은 —로 표시합니다. 0실적이나 ROAS 0%로 간주하지 않습니다.';
    var available = data && data.ready;
    dashboardBreakdown('dashboardDelivery', available ? data.delivery : null,
      [['active', '어제 집행 확인'], ['inactive', '어제 실적 없음'], ['unknown', '미확인']]);
    dashboardBreakdown('dashboardConfiguration', available ? data.configuration : null,
      [['enabled', '설정상 운영 가능'], ['disabled', '운영 가능 캠페인 없음'], ['unknown', '설정 미확인']]);
    $('dashboardReload').disabled = !data && !error;
  }
  function openDashboard() {
    var gen = state.gen, sel = state.selection, requestedDay = kstDay();
    show('dashboard');
    state.dashboard = null;
    state.loadedDay = null;
    renderDashboard(null);
    return api('GET', '/dashboard?selection=' + encodeURIComponent(sel)).then(function (data) {
      if (gen !== state.gen || sel !== state.selection) return;
      // 자정 전 요청의 옛 기간을 새 날짜의 자료로 남기지 않는다.
      if (requestedDay !== kstDay()) { state.gen++; return openDashboard(); }
      state.dashboard = data;
      state.loadedDay = requestedDay;
      renderDashboard(data);
    }, function (error) {
      if (gen !== state.gen || sel !== state.selection || (error && error.status === 401)) return;
      state.dashboard = null;
      renderDashboard(null, error);
    });
  }

  // ── 🛰 관제 ───────────────────────────────────────────────────────
  function clearWatch(message) {
    state.board = null;
    put($('issues'), message);
    put($('kpis')); put($('iwan')); put($('upbox')); put($('doneList'));
    $('upbox').hidden = true;
    $('doneList').hidden = true;
    $('doneToggle').textContent = '오늘 풀린 것 · 예외 처리한 것 —';
    $('doneToggle').setAttribute('aria-expanded', 'false');
    put($('tbody'), h('tr', null, h('td', { colspan: 9, class: 'empty' }, '현재 범위의 자료를 확인 중입니다.')));
    $('iss-n').textContent = '';
    $('tbl-n').textContent = '';
  }
  function openWatch() {
    var gen = state.gen;
    show('watch');
    var sel = state.selection;
    if (!state.board || state.board.selection !== sel) clearWatch(h('div', { class: 'loading' }, '불러오는 중…'));
    return api('GET', '/board?selection=' + encodeURIComponent(sel) + '&attention=0').then(function (b) {
      if (gen !== state.gen || sel !== state.selection) return;   // 늦게 온 옛 응답(범위를 빨리 바꿈)은 버린다
      state.board = b;
      state.loadedDay = kstDay();
      renderWatch();
      loadLinks();   // 「확인할 짝 N건」 — 접혀 있어도 수는 보인다(범위는 서버가 최대 범위로)
      if (fullCollectionAllowed()) loadCollection();
      if (state.endedOpen) loadEnded();
      if (state.focus === 'issues') $('issuesCard').scrollIntoView();
      if (state.focus === 'links') $('linksCard').scrollIntoView();
      if (state.focus === 'ended') $('endedCard').scrollIntoView();
      state.focus = null;
    }, function (e) {
      if (gen !== state.gen || (e && e.status === 401)) return;
      if (state.board && state.board.selection === sel) { toast(errText(e)); return; }
      // 첫 불러오기 실패 · 다른 범위로 바꾸다 실패 — 옛 숫자를 그대로 두지 않는다
      clearWatch(h('div', { class: 'empty' }, '관제 판을 불러오지 못했습니다 — ' + errText(e) + ' ',
        h('button', { type: 'button', class: 'btn sm', onclick: function () { state.gen++; openWatch(); } }, '다시 불러오기')));
      put($('tbody'), h('tr', null, h('td', { colspan: 9, class: 'empty' }, '불러오지 못했습니다.')));
    });
  }
  var INVENTORY_MAPPING = { matched: '전산 업체 매칭', no_erp_record: '전산 내에 등록된 업체 정보 없음', unclassified: '미분류 · 확인 필요' };
  function inventoryCardFilter(mapping, view) {
    state.inventoryMapping = mapping; state.inventoryView = view;
    state.inventoryWorkflow = 'all'; state.inventoryQ = '';
    $('inventoryMapping').value = mapping; $('inventoryView').value = view;
    $('inventoryWorkflow').value = 'all'; $('inventorySearch').value = '';
    loadInventory();
  }
  function renderInventorySummary(data, message) {
    var s = data && data.summary, ready = s && s.ready, counts = data && data.counts || {};
    var plan = data && data.collection_plan;
    $('inventoryCadence').textContent = !plan ? message || '수집 주기 확인 전' :
      '일일 대상 ' + num(plan.daily.total) + ' · 완료 ' + num(plan.daily.complete) + ' · 대기 ' + num(plan.daily.pending) +
      ' · 재시도 ' + num(plan.daily.retry) + ' · 확인 필요 ' + num(plan.daily.limited) +
      ' / 일요일 대상 ' + num(plan.weekly.total) + ' · 이번 주 완료 ' + num(plan.weekly.complete) +
      ' · 대기 ' + num(plan.weekly.pending) + ' · 재시도 ' + num(plan.weekly.retry) + ' · 확인 필요 ' + num(plan.weekly.limited) +
      ' / 정책 판단 보류 ' + num(plan.blocked.total) + ' · 비관리는 주 1회 점검이며 즉시 감지가 아닙니다.';
    var money = s && s.balance || {}, partial = !money.complete;
    var cards = [
      ['total', '이관 광고 계정', s ? num(s.current_total) : '—', '현재 이관 목록 · 빠짐 계정 제외', 'all', 'current'],
      ['matched', '매칭 완료', ready ? num(counts.matched) : '—', '전산 업체와 연결됨', 'matched', 'current'],
      ['unknown', '업체 미확인', ready ? num(counts.no_erp_record) : '—', '연결 근거 없음 · 미등록 확정 아님', 'no_erp_record', 'current'],
      ['unclassified', '미분류', ready ? num(counts.unclassified) : '—', '중복 후보·번호·원천 확인 필요', 'unclassified', 'current'],
      ['lost', '이관 빠짐', s && s.lost_count !== null ? num(s.lost_count) : '—', '2일·20시간 이상 부재 · 현재 총수와 별도', 'all', 'lost'],
      ['balance', '확인된 잔액 합계', won(money.known_sum), s ?
        (money.total_count === 0 && ready ? '대상 계정 없음' : '확인 ' + num(money.known_count) + ' / ' + num(money.total_count) + '계정 · 미확인 ' +
          num(Math.max(0, money.total_count - money.known_count)) + (partial ? ' · 전체 합계 아님' : '') + ' · 계정별 확인 시각은 아래 목록 참조') : '잔액 확인 중', 'all', 'balance_known']
    ];
    put($('inventorySummary'), cards.map(function (c) {
      var active = !!s && state.inventoryMapping === c[4] && state.inventoryView === c[5];
      return h('button', { type: 'button', class: 'inventory-stat ' + c[0], id: 'inventory-stat-' + c[0],
        disabled: !s, 'aria-pressed': String(active), onclick: function () { inventoryCardFilter(c[4], c[5]); } },
        h('span', { class: 'label' }, c[1]), h('strong', { class: 'value' }, c[2]),
        h('span', { class: 'note' }, message || (s && !ready ? '원천 자료 확인 필요 · 확정 집계 보류' : c[3])));
    }));
  }
  function loadInventory() {
    var gen = ++state.inventoryGen, sel = state.selection, pageGen = state.gen;
    closeModals();
    state.inventory = null;
    renderManagedCoverage(null);
    renderInventorySummary(null, '불러오는 중…');
    $('inventoryCount').textContent = '';
    $('inventorySource').textContent = '현재 권한으로 목록을 불러오는 중입니다.';
    put($('inventoryRows'), h('tr', null, h('td', { colspan: 9, class: 'empty' }, '불러오는 중…')));
    return api('GET', '/accounts?selection=' + encodeURIComponent(sel) + '&workflow=' +
      encodeURIComponent(state.inventoryWorkflow) + '&mapping=' + encodeURIComponent(state.inventoryMapping) +
      '&view=' + encodeURIComponent(state.inventoryView)).then(function (data) {
      if (gen !== state.inventoryGen || pageGen !== state.gen || sel !== state.selection || !state.me) return;
      state.inventory = data;
      renderInventory();
    }, function (e) {
      if (gen !== state.inventoryGen || pageGen !== state.gen || sel !== state.selection || (e && e.status === 401)) return;
      $('inventorySource').textContent = '목록을 불러오지 못했습니다. 목록 새로고침으로 다시 확인해 주세요.';
      renderManagedCoverage(null, '불러오지 못했습니다 · 목록 새로고침으로 다시 확인해 주세요.');
      renderInventorySummary(null, '불러오지 못했습니다 · 목록 새로고침으로 확인해 주세요.');
      put($('inventoryRows'), h('tr', null, h('td', { colspan: 9, class: 'empty' }, errText(e))));
    });
  }
  function renderInventory() {
    var data = state.inventory;
    if (!data) return;
    renderInventorySummary(data);
    renderManagedCoverage(data.managed_coverage);
    var query = state.inventoryQ.toLocaleLowerCase();
    var rows = data.rows.filter(function (r) {
      return [r.account_name, r.company_name, r.ad_account_no].join(' ').toLocaleLowerCase().indexOf(query) !== -1;
    });
    $('inventoryCount').textContent = (data.view === 'lost' ? '이관 빠짐 ' + num(rows.length) + '계정 · 현재 이관 ' + num(data.total) :
      num(rows.length) + ' / ' + num(data.total)) + '계정 · 매칭 ' +
      num(data.counts.matched) + ' · 업체 미확인 ' + num(data.counts.no_erp_record) + ' · 미분류 ' + num(data.counts.unclassified);
    $('inventorySource').textContent = '이관 목록 ' + (mdhm(data.accounts_at) || '수신 전') + ' · 전산 전체 목록 ' +
      (mdhm(data.catalog_at) || '수신 전') + (data.catalog_status !== 'accepted' || !data.accounts_current || data.matching_ready === false ?
      ' · 원본 확인 필요: 미등록 판정 및 직원 연결 표시를 보류합니다.' : ' · 목록 새로고침은 저장된 최신 결과를 다시 표시합니다.');
    var collection = { ok: '수집 완료', partial: '일부 수집', pending: '수집 대기', failed: '수집 실패',
      retry: '재시도 대기', reading: '수집 중', running: '수집 중', reauth_required: '네이버 접근 권한 확인',
      limited: '수집 중단 · 사유 확인', denied: '접근 권한 확인', blocked: '접근 권한 확인', not_current: '수집 대상 제외 · 이관 빠짐' };
    var collectionReason = { CHECKPOINT_PENDING: '남은 캠페인은 다음 회차에 이어 읽습니다',
      CHECKPOINT_INVALID: '중간 저장 자료 검증 실패 · 관리자 확인 필요', RETRY_EXHAUSTED: '연속 재시도 4회 소진 · 관리자 확인 필요',
      STATS_INCOMPLETE: '네이버 통계 일부 미수신', STATS_SHAPE: '네이버 통계 응답 형식 확인 필요',
      KEY_REJECTED: '계정 이관·조회 권한 확인 필요', CAMPAIGNS_CHANGED: '수집 중 캠페인 목록 변경 · 다시 확인',
      REQUEST_BUDGET: '회차 호출·시간 한도 도달', UNEXPECTED: '수집 오류 · 관리자 확인 필요' };
    put($('inventoryRows'), rows.length ? rows.map(function (r) {
      var c = r.collection || {}, m = r.management || {}, status = collection[c.status] || c.status || '수집 대기';
      if (m.cadence === 'weekly' && (!c.status || c.status === 'pending')) status = '비관리 · 일요일 7일 점검 대기';
      var period = periodText(c.period_start, c.period_end);
      var spend = c.spend === undefined ? c.yday_spend : c.spend;
      var hasValues = typeof spend === 'number' && isFinite(spend);
      var previous = (hasValues || !!c.last_success_at) && (c.stale === true || c.status !== 'ok');
      var company = r.detail_available ? h('button', { type: 'button', class: 'btn sm', onclick: function () {
        go('/naver/clients/' + r.possibility_id);
      } }, r.company_name || '전산 업체') : r.company_name || '—';
      return h('tr', { 'data-account': r.ad_account_no },
        h('td', null, r.account_name || '계정 이름 없음', h('span', { class: 'w' }, 'ID ' + (r.ad_account_no || '확인 필요')), adReasons(r)),
        h('td', null, company),
        h('td', { title: r.mapping === 'no_erp_record' ? data.no_erp_note : '' }, INVENTORY_MAPPING[r.mapping] || '미분류'),
        h('td', null, r.workflow), h('td', null, r.owner && r.owner.name || '담당 미확인'),
        h('td', null, status, c.error_code ? h('span', { class: 'w', title: c.error_code }, collectionReason[c.error_code] || c.error_code) : null,
          h('span', { class: 'w' }, '최근 시도 ' + datedTime(c.checked_at)),
          c.activity_observed === true && m.cadence === 'weekly' ? h('span', { class: 'blocked-note' }, '비관리 계정에 실적 있음 · 담당 확인') : null),
        h('td', { class: 'account-values' }, h('span', { class: 'w' }, previous ? '이전 성공값 · 최신 확인 필요' : hasValues ? '확인된 실적' : '성공 실적 없음'),
          h('span', { class: 'w' }, period), h('b', { class: 'num' }, won(spend)),
          h('span', { class: 'w' }, '노출 ' + num(c.imp === undefined ? c.yday_imp : c.imp) + ' · 클릭 ' + num(c.clk === undefined ? c.yday_clk : c.clk)),
          c.last_success_at ? h('span', { class: 'w' }, '마지막 성공 ' + datedTime(c.last_success_at)) : null),
        h('td', { class: 'account-values' }, h('b', { class: 'num' }, won(c.bizmoney)),
          h('span', { class: 'w' }, '잔액 확인 ' + datedTime(c.bizmoney_at)), c.stale === true && typeof c.bizmoney === 'number' ? h('span', { class: 'w' }, '이전 잔액 · 최신 확인 필요') : null,
          typeof c.bizmoney_change === 'number' && isFinite(c.bizmoney_change) && c.previous_bizmoney_at ?
            h('span', { class: 'w' }, '이전 조회 대비 잔액 ' + (c.bizmoney_change > 0 ? '증가 ' : c.bizmoney_change < 0 ? '감소 ' : '변화 없음 ') + won(Math.abs(c.bizmoney_change)),
              h('span', { class: 'w' }, '비교 기준 ' + datedTime(c.previous_bizmoney_at)),
              h('span', { class: 'w' }, '잔액 변화만으로 충전을 확정하지 않습니다.')) : null),
        h('td', null, { daily: '실관리 · 일일 점검', weekly: '비관리 · 일요일 7일 점검', blocked: '관리 판단 보류' }[m.cadence] || '관리 정보 확인 전',
          m.excluded === true ? h('span', { class: 'w' }, '수동 제외됨') : null,
          m.reason ? h('span', { class: 'w' }, managementReason(m.reason)) : null,
          managementActions(r)));
    }) : h('tr', null, h('td', { colspan: 9, class: 'empty' }, '이 조건에 해당하는 계정이 없습니다. 매칭 상태·업무 단계·검색어를 확인해 주세요.')));
  }
  function adCode(label, value) {
    value = value || {};
    var raw = value.code === null || value.code === undefined ? '원문 미제공' : value.code === '' ? '빈 문자열' : value.code;
    var stateText = { known: '확인된 코드', unknown: '알 수 없는 코드', not_provided: '코드 미제공' };
    return h('p', null, label + ' ', h('code', { class: 'ad-raw-code' }, raw),
      h('span', { class: 'w' }, (value.meaning || '해석 미확인') + ' · ' + (stateText[value.code_state] || '코드 해석 상태 미확인')));
  }
  function adReasonItem(item, parent) {
    var levels = { campaign: '캠페인', adgroup: '광고그룹', keyword: '키워드', ad: '소재', ad_extension: '확장소재', business_channel: '사업채널' };
    return h('div', { class: 'ad-reason-item' }, h('b', null, (parent ? '상위 ' : '') + (levels[item.entity] || '알 수 없는 계층') + ' · ' + (item.entity_id || 'ID 미제공')),
      h('span', { class: 'w' }, '실제 확인 ' + datedTime(item.checked_at)), adCode('status', item.status), adCode('statusReason', item.reason),
      parent ? null : (item.parents || []).map(function (p) { return adReasonItem(p, true); }));
  }
  function adReasons(row) {
    var status = { pending: '구조 미조회', reading: '구조 조회 중', retry: '구조 재시도 대기',
      limited: '구조 조회 제한 · 확인 필요', reauth_required: '구조 조회 권한 확인 필요',
      partial: '구조 일부 조회', ok: '구조 조회 완료' }[row.structure_status] || '구조 조회 상태 미확인';
    var inventory = state.inventory, gen = state.gen, selection = state.selection, busy = false;
    var content = h('div'), detail;
    function fresh() { return state.inventory === inventory && state.gen === gen && state.selection === selection; }
    function load(page) {
      if (busy || !fresh()) return;
      busy = true; put(content, h('p', { class: 'w' }, '저장된 사유를 불러오는 중…'));
      api('GET', '/accounts/reasons?ad_account_no=' + encodeURIComponent(row.ad_account_no) + '&page=' + page + '&selection=' + encodeURIComponent(selection)).then(function (data) {
        if (!fresh()) return;
        busy = false;
        put(content, h('p', { class: 'w' }, '저장된 사유 ' + num(data.total) + '건 · ' + num(data.page + 1) + '페이지 · 실제 확인 ' + datedTime(data.checked_at)),
          (data.items || []).map(function (item) { return adReasonItem(item, false); }),
          data.total === 0 ? h('p', { class: 'w' }, '저장된 광고 상태 응답이 없습니다. 사유 없음·정상을 뜻하지 않습니다.') : null,
          h('div', { class: 'account-actions' },
            data.page > 0 ? h('button', { type: 'button', class: 'btn sm', onclick: function () { load(data.page - 1); } }, '이전 사유') : null,
            data.next_page !== null && data.next_page !== undefined ? h('button', { type: 'button', class: 'btn sm', onclick: function () { load(data.next_page); } }, '다음 사유') : null));
      }, function (e) {
        if (!fresh()) return;
        busy = false;
        put(content, h('p', { class: 'w' }, '사유를 확인하지 못했습니다. ' + errText(e)),
          h('button', { type: 'button', class: 'btn sm', onclick: function () { load(page); } }, '사유 다시 보기'));
      });
    }
    detail = h('details', { class: 'ad-reasons', ontoggle: function () {
      if (detail.open && !content.firstChild) load(0);
    } }, h('summary', null, '광고 상태·사유 ' + num(row.ad_reason_count) + '건 · 펼쳐 보기'),
      h('p', { class: 'w' }, status + ' · ' + datedTime(row.structure_checked_at)),
      h('p', { class: 'w' }, '미조회 항목은 정상 판정 아님 · 설정상 노출 가능과 실제 집행은 다릅니다. 매칭·수집 실패 사유와 별개입니다.'),
      content);
    return detail;
  }
  var managementEdit = null;
  function managementReason(code) {
    var labels = { AUTHORITY_INVALID: '네이버 이관·조회 권한 확인 필요', SOURCE_STALE: '최신 원천 확인 전 · 변경 보류',
      UNMATCHED_ACCOUNT: '전산 업체 연결 전', UNKNOWN_STAGE: '업무 단계 확인 전', MANUAL_EXCLUSION: '담당자가 관제 제외',
      MANUAL_INCLUSION: '담당자가 관제 포함', MANAGED_STAGE: '실관리 4단계', NONMANAGED_STAGE: '실관리 외 단계' };
    return labels[code] || '알 수 없는 관리 사유 (' + code + ')';
  }
  function managementCapability(path, body) {
    if (!state.me || !state.inventory || parse(location.pathname).screen !== 'transfers' || !body) return false;
    var row = (state.inventory.rows || []).filter(function (r) { return r.ad_account_no === body.ad_account_no; })[0];
    var m = row && row.management || {};
    if (m.cadence !== 'daily' && m.cadence !== 'weekly') return false;
    if (path === '/management/collect') return m.can_collect === true;
    return path === '/management/update' && m.can_manage === true && typeof m.stage_revision === 'string' &&
      !!m.stage_revision && m.stage_revision === body.stage_revision;
  }
  function managementActions(row) {
    var m = row.management || {}, actions = [], inventory = state.inventory, gen = state.gen;
    var fresh = function () { return state.inventory === inventory && state.gen === gen; };
    if (managementCapability('/management/update', { ad_account_no: row.ad_account_no, stage_revision: m.stage_revision })) {
      actions.push(h('button', { type: 'button', class: 'btn sm', onclick: function (ev) {
        if (!fresh()) return;
        managementEdit = { row: row, inventory: inventory, gen: gen, included: m.cadence !== 'daily' };
        $('managementTitle').textContent = managementEdit.included ? '관제 포함' : '관제 제외';
        $('managementDescription').textContent = (row.company_name || row.account_name || '이 계정') + ' · 광고 계정 ID ' + row.ad_account_no;
        $('managementReason').value = '';
        $('managementSave').textContent = managementEdit.included ? '관제 포함 저장' : '관제 제외 저장';
        openModal('m-management', ev.currentTarget); $('managementReason').focus();
      } }, m.cadence === 'daily' ? '관제 제외' : '관제 포함'));
    }
    if (managementCapability('/management/collect', { ad_account_no: row.ad_account_no })) {
      actions.push(h('button', { type: 'button', class: 'btn sm', onclick: function (ev) {
        if (!fresh() || !managementCapability('/management/collect', { ad_account_no: row.ad_account_no })) return;
        once('management-collect:' + row.ad_account_no, ev.currentTarget, function () {
          return api('POST', '/management/collect', { ad_account_no: row.ad_account_no }).then(function () {
            if (!fresh()) return;
            toast('조회 요청을 받았습니다 · 완료 여부는 수집 결과에서 확인해 주세요.'); loadInventory();
          }, function (e) { if (fresh()) toast(errText(e)); });
        });
      } }, '지금 조회'));
    }
    return actions.length ? h('div', { class: 'account-actions' }, actions) : h('span', { class: 'w' }, '이 범위에서는 조회·변경할 수 없습니다');
  }
  function saveManagement() {
    var edit = managementEdit;
    if (!edit || edit.inventory !== state.inventory || edit.gen !== state.gen) return;
    var reason = $('managementReason').value.trim();
    if (!reason) { toast('변경 사유를 적어 주세요'); $('managementReason').focus(); return; }
    var body = { ad_account_no: edit.row.ad_account_no, stage_revision: edit.row.management.stage_revision, included: edit.included, reason: reason };
    if (!managementCapability('/management/update', body)) return;
    once('management-update:' + edit.row.ad_account_no, $('managementSave'), function () {
      return api('POST', '/management/update', body).then(function () {
        if (edit.gen !== state.gen || edit.inventory !== state.inventory) return;
        closeModals(); toast((edit.included ? '관제 포함' : '관제 제외') + '를 저장했습니다 · 전산 단계·광고는 변경하지 않았습니다.'); loadInventory();
      }, function (e) { if (edit.gen === state.gen && edit.inventory === state.inventory) toast(errText(e)); });
    });
  }
  var COVERAGE_STATE = { matched: '연결 확인', id_missing: '번호 미입력', identifier_invalid: '번호 형식 확인',
    identifier_conflict: '번호 충돌 · 대표 확인', multiple_candidates: '후보 여러 개', candidate_pending: '후보 확인 전',
    transfer_unconfirmed: '이관 확인 필요', no_candidate: '일치 후보 없음', source_unavailable: '원천 자료 확인 필요' };
  var MATCHING_REASON = { ID_MISSING: '네이버 관제용 광고 계정 ID 미입력', MULTIPLE_CANDIDATES: '동일 이름 후보 여러 개',
    CANDIDATE_PENDING: '후보 연결 확인 전', NO_CANDIDATE: '연결 후보 없음', SOURCE_UNAVAILABLE: '최신 자료를 확인하지 못함',
    CONFIRMED_ACCOUNT_NOT_LISTED: '기존 확정 계정이 현재 이관 목록에 없음', 'customer-id-format': '고객 ID 형식 오류',
    'customer-id-length': '고객 ID 자릿수 오류', 'not-linked': '고객 ID가 이관 목록에 없음',
    'ad-account-number': '고객 ID와 광고 계정 ID 구분 필요', 'ambiguous-space': '고객 ID·계정 ID 간 충돌',
    'claimed-by-several': '여러 업체가 같은 번호 사용', 'confirmed-elsewhere': '다른 업체에 이미 확정됨',
    'rejected-by-human': '이 조합은 아님으로 확인됨', 'name-different': '번호와 업체 이름 불일치',
    'name-points-elsewhere': '계정 이름이 다른 업체와 일치', 'ad-account-id-format': '광고 계정 ID 형식 오류',
    'ad-account-not-linked': '광고 계정 ID가 이관 목록에 없음', 'account-identifiers-conflict': '두 ID가 서로 다른 계정 지칭' };
  function renderManagedCoverage(data, message) {
    var ready = data && data.ready === true;
    $('coverageStatus').textContent = ready ? '실관리 ' + num(data.total) + ' · 연결 확인 ' + num(data.matched) + ' · 확인 필요 ' + num(data.missing) :
      message || (data ? '원천 자료 확인 필요 · 확정 집계 보류' : '불러오는 중…');
    put($('coverageRows'), data && (data.items || []).length ? data.items.map(function (r) {
      var status = ready ? r.state : 'source_unavailable';
      var action = status === 'matched' ? '아래 계정 목록에서 관리·수집 상태 확인' :
        status === 'source_unavailable' ? '자료 동기화 확인 후 목록 새로고침' :
        status === 'identifier_conflict' ? '대표에게 번호 중복·기존 연결 확인 요청' :
        status === 'transfer_unconfirmed' ? '네이버 대행 이관 상태와 전산 번호 확인' :
        status === 'candidate_pending' || status === 'multiple_candidates' ? '원본 광고 계정 ID 대조 후 전산 입력 · 짝 확인' : '전산 업체 계정 정보에서 광고 계정 ID 확인';
      return h('tr', null, h('td', null, r.company_name || '업체 이름 없음', h('span', { class: 'w' }, r.workflow || '단계 미확인')),
        h('td', null, COVERAGE_STATE[status] || status, (ready ? r.codes || [] : ['SOURCE_UNAVAILABLE']).map(function (code) {
          return h('span', { class: 'w' }, (MATCHING_REASON[code] || '알 수 없는 매칭 사유') + ' (' + code + ')');
        })), h('td', { class: 'num' }, ready ? num(r.matched_account_count) + ' / ' + num(r.candidate_count) : '— / —'),
        h('td', { class: 'wrap' }, action, ready && (status === 'candidate_pending' || status === 'multiple_candidates') ?
          h('button', { type: 'button', class: 'btn sm', onclick: function () { go('/naver/links'); } }, '짝 확인 열기') : null));
    }) : h('tr', null, h('td', { colspan: 4, class: 'empty' }, ready ? '현재 담당 범위에 실관리 업체가 없습니다.' : message || '최신 자료를 확인하기 전에는 연결 완료로 판단하지 않습니다.')));
  }
  // 보고서는 서버 집계·완결 여부를 그대로 표시한다. 검토는 게시·전송이 아니다.
  function loadReports(page) {
    page = typeof page === 'number' && page >= 0 ? page : 0;
    var gen = ++state.reportsGen, pageGen = state.gen, sel = state.selection;
    closeModals(); state.reports = null;
    $('reportsSchedule').textContent = '예약 시각 확인 중…';
    $('reportsStatus').textContent = '현재 담당 범위의 보고서를 불러오는 중…';
    put($('reportsRows')); put($('reportsPages'));
    return api('GET', '/reports?selection=' + encodeURIComponent(sel) + (page ? '&page=' + page : '')).then(function (data) {
      if (gen !== state.reportsGen || pageGen !== state.gen || sel !== state.selection || !state.me) return;
      state.reports = data;
      var schedule = data.schedule || {};
      $('reportsSchedule').textContent = '주간 ' + (schedule.weekly || '예약 미확인') + ' · 월간 ' + (schedule.monthly || '예약 미확인') +
        ' · ' + (schedule.timezone || '시간대 미확인');
      var rows = data.rows || [];
      $('reportsStatus').textContent = '보고서 ' + num(typeof data.total === 'number' ? data.total : rows.length) + '건 · ' + num(page + 1) + '페이지 · 누락 자료는 0으로 채우지 않습니다 · 게시·전송 기능 없음';
      put($('reportsRows'), rows.length ? rows.map(reportCard) : h('div', { class: 'card empty' }, '현재 담당 범위에 생성된 보고서가 없습니다. 확정 계정·수집 기간과 예약 시각을 확인해 주세요.'));
      function turnPage(target) {
        if (gen === state.reportsGen && pageGen === state.gen && sel === state.selection && state.reports === data) loadReports(target);
      }
      put($('reportsPages'), page > 0 ? h('button', { type: 'button', class: 'btn', onclick: function () { turnPage(page - 1); } }, '이전 보고서') : null,
        typeof data.next_page === 'number' ? h('button', { type: 'button', class: 'btn', onclick: function () { turnPage(data.next_page); } }, '다음 보고서') : null);
    }, function (e) {
      if (gen !== state.reportsGen || pageGen !== state.gen || sel !== state.selection || (e && e.status === 401)) return;
      $('reportsSchedule').textContent = '예약 시각을 확인하지 못했습니다.';
      $('reportsStatus').textContent = '보고서를 불러오지 못했습니다 · ' + errText(e);
      put($('reportsRows'), h('div', { class: 'card empty' }, '보고서 새로고침으로 다시 확인해 주세요. 이전 담당 범위의 보고서는 표시하지 않습니다.'));
    });
  }
  function reportMetric(label, value) { return h('div', null, h('dt', null, label), h('dd', { class: 'num' }, value)); }
  function reportCard(row) {
    var p = row.payload || {}, period = p.period || {}, totals = p.totals || {}, ratios = p.ratios || {}, coverage = p.coverage || {};
    var status = { ready: '집계 완료', partial: '부분 집계 · 전체 합계 아님', collecting: '수집 중 · 자료 부족' }[row.status] || '알 수 없는 집계 상태 (' + (row.status || '미제공') + ')';
    var review = { needs_staff_review: '담당 검토 필요', not_required: '필수 검토 대상 아님', approved: '담당 검토 승인', held: '담당 검토 보류' }[row.review_status] || '검토 상태 미확인';
    var missing = Array.isArray(p.missing) ? p.missing : null;
    var missingCount = typeof p.missing_count === 'number' ? p.missing_count : missing ? missing.length : null;
    var metricNames = { imp: '노출', impressions: '노출', clk: '클릭', clicks: '클릭', spend: '광고비', conversions: '전환', conversion_value: '전환 매출' };
    var missingReasons = { source_unverified: '원천 확인 전', metrics_incomplete: '일부 지표 미수신', day_missing: '해당 날짜 미수집' };
    return h('article', { class: 'card report-card', 'data-report': row.report_id },
      h('div', { class: 'kh' }, h('h2', null, row.company_name || '업체 이름 없음'),
        h('span', { class: 'n' }, ({ monthly: '월간', weekly: '주간' }[period.kind] || '보고 기간 미확인') + ' · ' + periodText(period.start, period.end))),
      h('p', { class: 'report-state' }, status, h('span', { class: 'pill ' + (row.review_status === 'approved' ? 'p-green' : 'p-gray') }, review)),
      h('p', { class: 'report-meta' }, '생성 ' + datedTime(row.generated_at) + ' · 담당 ' + (row.owner && row.owner.name || '미확인')),
      h('dl', { class: 'report-metrics' },
        reportMetric(coverage.basic_complete === true ? '광고비' : '확인된 광고비', won(totals.spend)),
        reportMetric('노출', num(totals.impressions)), reportMetric('클릭', num(totals.clicks)),
        reportMetric('전환', num(totals.conversions)), reportMetric('CTR', percent(ratios.ctr)),
        reportMetric('CPC', won(ratios.cpc)), reportMetric('ROAS', percent(ratios.roas))),
      h('p', { class: 'report-meta' }, '계정×일 확인: 기본 지표 ' + num(coverage.basic_complete_account_days) + ' / ' + num(coverage.expected_account_days) +
        ' · 전환 지표 ' + num(coverage.conversion_complete_account_days) + ' / ' + num(coverage.expected_account_days) + ' · 미수집·미연동은 — 표시'),
      h('p', { class: 'report-meta' }, 'ROAS는 광고비·전환 매출이 함께 확인된 계정×일만 사용 · 대상 ' + num(ratios.roas_account_days)),
      h('details', { class: 'report-missing' }, h('summary', null, missing ? '누락 ' + num(missingCount) + '건 · 날짜·지표 확인' : '누락 정보 미확인'),
        missing && missing.length ? h('ul', null, missing.slice(0, 100).map(function (m) {
          return h('li', null, (m.day || '날짜 미확인') + ' · 계정 순번 ' + num(m.account_index) + ' · ' +
            (missingReasons[m.reason] || '알 수 없는 누락 사유 (' + (m.reason || '미제공') + ')') + ' · ' +
            (m.metrics || []).map(function (k) { return metricNames[k] || k; }).join('·'));
        }), missingCount > 100 ? h('li', null, '앞 100건 표시 · 전체 누락 ' + num(missingCount) + '건') : null) :
          h('p', null, missing ? '서버가 보고한 누락이 없습니다.' : '원천 자료의 누락 여부를 확인하지 못했습니다.')),
      (p.blocked_reasons || []).map(function (code) { return h('p', { class: 'blocked-note' },
        ({ no_confirmed_accounts: '확정 계정 없음 · 계정 연결 확인', not_due: '보고 기간 마감·생성 예약 전' }[code] || '알 수 없는 집계 보류 사유') + ' (' + code + ')'); }),
      h('p', { class: 'report-meta' }, '검토는 내부 기록입니다. 광고주 공유·전송은 하지 않습니다.'), reportActions(row));
  }
  var reportEdit = null;
  function reportCapability(path, body) {
    if (path !== '/reports/review' || !body || !state.me || !state.reports || parse(location.pathname).screen !== 'reports') return false;
    var row = (state.reports.rows || []).filter(function (r) { return r.report_id === body.report_id; })[0];
    return !!row && row.can_review === true && (body.decision === 'held' || body.decision === 'approved' && row.status === 'ready');
  }
  function reportActions(row) {
    var reports = state.reports, gen = state.gen;
    var buttons = [['approved', '검토 승인'], ['held', '검토 보류']].filter(function (action) {
      return reportCapability('/reports/review', { report_id: row.report_id, decision: action[0] });
    }).map(function (action) {
      return h('button', { type: 'button', class: 'btn sm', onclick: function (ev) {
        if (reports !== state.reports || gen !== state.gen) return;
        reportEdit = { row: row, reports: reports, gen: gen, decision: action[0], label: action[1] };
        $('reviewTitle').textContent = action[1];
        var p = row.payload && row.payload.period || {};
        $('reviewDescription').textContent = (row.company_name || '업체 이름 미확인') + ' · ' + periodText(p.start, p.end);
        $('reviewNote').value = ''; $('reviewSave').textContent = action[1] + ' 저장';
        openModal('m-report-review', ev.currentTarget); $('reviewNote').focus();
      } }, action[1]);
    });
    return buttons.length ? h('div', { class: 'report-actions' }, buttons) :
      h('p', { class: 'blocked-note' }, row.status !== 'ready' ? '집계 완료 전에는 승인할 수 없습니다. 수집 상태·누락을 확인해 주세요.' : '현재 담당 권한·자료 상태에서는 검토를 저장할 수 없습니다.');
  }
  function saveReportReview() {
    var edit = reportEdit;
    if (!edit || edit.reports !== state.reports || edit.gen !== state.gen) return;
    var note = $('reviewNote').value.trim();
    if (!note) { toast('검토 메모를 적어 주세요'); $('reviewNote').focus(); return; }
    var body = { report_id: edit.row.report_id, decision: edit.decision, note: note };
    if (!reportCapability('/reports/review', body)) return;
    once('report-review:' + edit.row.report_id, $('reviewSave'), function () {
      return api('POST', '/reports/review', body).then(function () {
        if (edit.gen !== state.gen || edit.reports !== state.reports) return;
        closeModals(); toast(edit.label + '을 저장했습니다 · 게시·전송하지 않았습니다.'); loadReports();
      }, function (e) { if (edit.gen === state.gen && edit.reports === state.reports) toast(errText(e)); });
    });
  }
  function fail(e) {
    if (e && e.status === 401) return;
    toast(errText(e));
  }
  function renderWatch() {
    renderRun();
    renderIwan();
    renderKpis();
    renderUp();
    renderIssues();
    renderTable();
    $('links-n').textContent = state.links ? state.links.rows.length + '건' : '';
    $('ended-n').textContent = state.ended ? state.ended.rows.length + '곳' : '';
  }
  function stageInputMessage() {
    var b = state.board.band;
    if (b.stage_state === 'held') return '계약 단계 목록을 확인 중이라 아직 광고주를 표시하지 않았습니다. 자동 반영이 보류된 상태이며 담당 광고주가 없다는 뜻은 아닙니다.';
    if (b.stage_state === 'not_accepted') return '계약 단계 목록이 아직 반영되지 않았습니다. 담당 광고주가 없는지 여부는 자료가 반영된 뒤 확인할 수 있습니다.';
    return '';
  }
  function resultsIncomplete() {
    var b = state.board.band, runs = b.runs || [], last = runs[runs.length - 1];
    return !!stageInputMessage() || !b.pairing_today || !last || last.status !== 'done' || state.board.counts.white > 0;
  }
  function renderRun() {
    var b = state.board.band, rb = $('runbar');
    var runs = b.runs || [], last = runs[runs.length - 1];
    var parts = [], cls = 'runbar';
    if (!last) {
      if (b.deadline_passed) { cls += ' bad'; parts.push(h('b', null, '오늘 점검 기록이 없습니다'), ' · 미점검은 정상 판정이 아닙니다. 자료 반영·점검 진행 상태를 확인해 주세요.'); }
      else { cls += ' wait'; parts.push(h('b', null, '오늘 점검 전'), readOnly() ? ' · 정기 점검 06:30 예약 · 현재 시간대에는 아직 수집·점검 전일 수 있습니다' : ' · 정기 점검 06:30 시작 · 08:00 마감 예정'); }
    } else if (last.status === 'running') {
      cls += ' wait'; parts.push(h('b', null, '오늘 점검 진행 중'), ' · ' + mdhm(last.started_at) + ' 시작');
    } else if (last.status === 'done') {
      parts.push('오늘 점검 ', h('b', { class: 'num' }, mdhm(last.started_at)), ' 시작 · ', h('b', { class: 'num' }, hm(last.finished_at)), ' 종료');
    } else {
      cls += ' bad'; parts.push(h('b', null, '오늘 점검이 끝나지 않았습니다'), ' · ' + mdhm(last.started_at) + ' 시작 · 끝내지 못한 광고주는 「오늘 점검 안 됨」(⚪)으로 보입니다' + (readOnly() ? ' · 검증판의 알림 전송은 꺼져 있습니다' : ' · 대표에게 알림이 갑니다'));
    }
    if (last && typeof last.accounts_total === 'number') {
      parts.push(' · 계정 ', h('b', { class: 'num' }, num(last.accounts_ok)), ' / ', h('b', { class: 'num' }, num(last.accounts_total)), ' 읽음');
    }
    if (!b.pairing_today) parts.push(' · 오늘 짝 맞추기 전(이관 칸은 받은 뒤에 보입니다)');
    if (stageInputMessage()) parts.push(' · ', h('b', null, stageInputMessage()));
    if (b.stage_as_of) parts.push(' · 계약 단계 자료 ' + mdhm(b.stage_as_of));
    if (b.pairing_at) parts.push(' · 짝 맞추기 자료 ' + mdhm(b.pairing_at));
    if (b.org_freshness === 'stale' || b.org_freshness === 'none') parts.push(' · ⚠ 조직 자료가 낡았습니다 — 🙈 예외 · 「이 계정 맞음」은 잠시 막힙니다');
    else if (b.org_freshness === 'yellow') parts.push(' · 조직 자료가 조금 늦었습니다');
    rb.className = cls;
    put(rb, h('span', { class: 'ok', 'aria-hidden': 'true' }), parts);
  }
  function renderIwan() {
    var L = state.board.links || {};
    function chip(key, cls, label) {
      var f = 'iw_' + key;
      return h('button', { type: 'button', class: 'ichip ' + cls + (state.filter === f ? ' on' : ''), 'aria-pressed': String(state.filter === f),
                           onclick: function () { setFilter(state.filter === f ? 'need' : f); } },
               label + ' ', h('b', { class: 'num' }, num(L[key] || 0)));
    }
    put($('iwan'), h('span', { class: 'lbl' }, '🔌 이관'), h('span', null, '이관됨 ', h('b', { class: 'num' }, num(L.listed || 0))),
        chip('broken', 'lost', '🔌 이관 빠짐'), chip('missing', '', '오늘 목록에 없음'), chip('unlinked_numbers', '', '이관 안 된 번호'),
        L.pending ? h('span', null, '짝 맞추기 전 ', h('b', { class: 'num' }, num(L.pending))) : null,
        h('span', { class: 'src' }, '대행 연결 목록 기준 · 이관 = 광고주 광고계정이 우리 회사에 연결된 상태'));
  }
  function renderKpis() {
    var c = state.board.counts;
    function k(key, cls, label, val, sub) {
      return h('button', { type: 'button', class: 'kpi ' + cls + (state.filter === key ? ' on' : ''), 'aria-pressed': String(state.filter === key),
                           onclick: function () { setFilter(key); } },
               h('span', { class: 'l' }, label), h('span', { class: 'v' }, num(val)), h('span', { class: 's' }, sub));
    }
    put($('kpis'),
        k('all', 'all', '전체 보기', c.total, '권한 범위의 모든 광고주'),
        k('need', 'need', '👉 확인 필요', c.needs_attention, '들어가 볼 곳'),
        k('red', 'red', [h('span', { class: 'sig red', 'aria-hidden': 'true' }), '긴급'], c.red, '오늘 안에'),
        k('yellow', 'yellow', [h('span', { class: 'sig yellow', 'aria-hidden': 'true' }), '주의'], c.yellow, '이번 주 안에'),
        k('green', 'green', [h('span', { class: 'sig green', 'aria-hidden': 'true' }), '정상'], c.green, '안 봐도 됨'),
        k('white', 'white', [h('span', { class: 'sig white', 'aria-hidden': 'true' }), '점검 불가'], c.white, '이관 · 읽기 · 점검 상태'));
  }
  function renderUp() {
    var up = watchItems(state.board.escalated_to_me), box = $('upbox');
    box.hidden = !up.length;
    if (!up.length) { put(box); return; }
    put(box, h('b', null, '⬆ 나에게 올라온 🟡 ' + up.length + '건'), ' — 12시간 넘게 👀 확인이 없어 한 단계 위로 올라왔습니다',
        h('ul', null, up.map(function (e) {
          return h('li', null, h('button', { type: 'button', class: 'link', onclick: function () { go('/naver/clients/' + e.possibility_id); } }, e.name || ''),
                   ' — ' + cause(e.code) + ' · ' + num(e.waited_hours) + '시간째');
        })));
  }
  function issueRow(i, where) {
    var st = i.state_now || i.state;
    var act = [];
    var can = readOnly() ? {} : (i.can || {});
    if (can.ack) act.push(h('button', { type: 'button', class: 'btn sm', onclick: function (ev) { hand(i, 'ack', undefined, ev.currentTarget); } }, '👀 확인 중'));
    if (can.resolve) act.push(h('button', { type: 'button', class: 'btn sm blue', onclick: function (ev) { hand(i, 'resolve', undefined, ev.currentTarget); } }, '✅ 해결'));
    if (can.except) act.push(h('button', { type: 'button', class: 'btn sm', onclick: function (ev) { askExcept(i, ev.currentTarget); } }, '🙈 예외…'));
    else if (can.except_blocked) act.push(h('span', { class: 'blocked-note' }, BLOCKED[can.except_blocked] || '🙈 지금은 예외를 줄 수 없음'));
    var who = i.hand ? ' · ' + (i.hand.by || '') + ' ' + mdhm(i.hand.at) : '';
    var memo = i.hand && i.hand.note ? h('span', { class: 'memo' }, '📝 ' + i.hand.note) : null;
    var until = st === 'exception' && i.exception_until ? ' · ' + md(i.exception_until) + '까지' : '';
    var again = i.reappear_count > 0 ? ' · 다시 생김 ' + i.reappear_count + '회' : '';
    var open = st === 'new' || st === 'ack';
    var sev = i.severity === 'red' ? 'red' : i.severity === 'yellow' ? 'yellow' : 'info';
    var owner = where === 'client' ? null : h('span', { class: 'who' }, (i.owner && i.owner.name) || '담당 미정');
    var name = where === 'client' ? null : [h('button', { type: 'button', class: 'link', onclick: function () { go('/naver/clients/' + i.possibility_id); } }, i.name || ''), owner, ' — '];
    var target = i.target_tail ? ' · 계정 ••••' + i.target_tail : '';
    return h('div', { class: 'iss' + (open ? '' : ' done'), 'data-issue': i.issue_id },
             h('span', { class: 'sig ' + sev, role: 'img', 'aria-label': COLOR_TEXT[sev] || '알아 두기' }),
             h('div', { class: 'tx' }, name, where === 'client' ? [h('b', null, cause(i.code)), fact(i) ? h('span', { class: 'w' }, fact(i)) : null]
               : (fact(i) || cause(i.code)),
               h('span', { class: 'w' }, h('span', { class: 'st ' + st }, STATE[st] || st), ' · 처음 ' + md(i.first_seen_on) + until + again + target + who),
               memo),
             h('div', { class: 'act' }, act));
  }
  function renderIssues() {
    var rows = watchItems(state.board.issue_rows), box = $('issues');
    var groups = [], at = {};
    rows.forEach(function (i) {
      var key = i.severity + '|' + i.code;
      if (!(key in at)) { at[key] = groups.length; groups.push({ sev: i.severity, code: i.code, items: [] }); }
      groups[at[key]].items.push(i);
    });
    var out = [];
    groups.forEach(function (g) {
      var info = g.sev !== 'red' && g.sev !== 'yellow';
      var seen = {}, places = 0;   // 곳 = 광고주 수(한 광고주의 계정 여럿은 한 곳)
      g.items.forEach(function (i) { if (!seen[i.possibility_id]) { seen[i.possibility_id] = true; places++; } });
      var n = places + '곳' + (g.items.length > places ? ' · 계정 ' + g.items.length + '개' : '');
      out.push(h('div', { class: 'cause' + (info ? ' info' : '') }, h('span', { class: 'sig ' + (info ? 'info' : g.sev), 'aria-hidden': 'true' }),
                 info ? 'ⓘ 알아 두기 · ' + cause(g.code) : cause(g.code), ' ', h('span', { class: 'n' }, n + (info ? ' · 이슈 아님 · 「확인 필요」에 세지 않음' : ''))));
      g.items.forEach(function (i) { out.push(issueRow(i)); });
    });
    put(box, out.length ? out : h('div', { class: 'empty' }, resultsIncomplete()
      ? '아직 점검 결과가 충분하지 않아 문제 여부를 판단할 수 없습니다. 미점검·점검 불가 항목과 자료 기준 시각을 확인해 주세요.'
      : '현재 조회 범위에서 열린 이슈가 없습니다. 오늘 점검 결과와 자료 기준 시각을 확인해 주세요.'));
    var red = rows.filter(function (i) { return i.severity === 'red'; }).length;
    $('iss-n').textContent = '열린 이슈 ' + rows.filter(function (i) { return i.severity !== 'info'; }).length + ' (긴급 ' + red + ')';
    var done = watchItems(state.board.done_rows);
    $('doneToggle').textContent = (state.doneOpen ? '접기 — ' : '') + '오늘 풀린 것 · 예외 처리한 것 ' + done.length + '건' + (state.doneOpen ? '' : ' 보기');
    $('doneToggle').setAttribute('aria-expanded', String(state.doneOpen));
    $('doneList').hidden = !state.doneOpen;
    put($('doneList'), done.length ? done.map(function (i) { return issueRow(i); }) : h('div', { class: 'empty' }, '없습니다.'));
  }
  function passes(r) {
    var f = state.filter;
    if (state.q && (r.name || '').indexOf(state.q) < 0) return false;
    if (f === 'iw_unlinked_numbers') return !!r.unlinked;
    if (f.indexOf('iw_') === 0) return r.link === f.slice(3);
    if (f === 'need') return r.verdict.needs_attention;
    if (f === 'all') return true;
    return r.verdict.color === f;
  }
  function watchRows() { return (state.board.rows || []).filter(passes); }
  function watchItems(items) {
    var ids = {};
    watchRows().forEach(function (r) { ids[r.possibility_id] = true; });
    return (items || []).filter(function (i) { return ids[i.possibility_id] === true; });
  }
  function renderWatchSelection() {
    if (!state.board) return;
    renderUp();
    renderIssues();
    renderTable();
  }
  function statusText(v) {
    if (v.color === 'white') return WHITE_TEXT[v.white_reason] || '점검 불가';
    if (v.color === 'red') return '긴급 이슈';
    if (v.color === 'yellow') return '주의 이슈';
    return '정상';
  }
  function row(r) {
    var v = r.verdict;
    var rel = REL[r.relation];
    var lk = LINK[r.link] || LINK.none;
    var open = (r.open_red || 0) + (r.open_yellow || 0);
    var biz = r.bizmoney;
    return h('tr', { class: 'click', 'data-pid': r.possibility_id, 'data-color': v.color,
                     onclick: function (ev) { if (ev.target.tagName !== 'BUTTON') go('/naver/clients/' + r.possibility_id); } },
             h('td', null, h('span', { class: 'sig ' + v.color, role: 'img', 'aria-label': COLOR_TEXT[v.color] }), h('span', { class: 'hint' }, statusText(v))),
             h('td', null, h('button', { type: 'button', class: 'link', onclick: function () { go('/naver/clients/' + r.possibility_id); } }, r.name || ''),
               r.account_unconfirmed ? [' ', h('span', { class: 'pill p-gray', title: '읽기 점검은 합니다. 자동화·광고주용 보고서는 계정 확인 뒤' }, '계정 확인 전')] : null,
               rel ? [' ', h('span', { class: 'who' }, rel)] : null),
             h('td', null, v.needs_attention ? h('span', { class: 'needdot' }, '확인 필요') : h('span', { class: 'noneed' }, '—')),
             h('td', null, h('span', { class: 'pill ' + lk[0] }, lk[1]),
               r.unlinked && r.link !== 'not_linked' ? [' ', h('span', { class: 'pill p-gray', title: '전산에 적힌 번호 중 우리 회사로 이관되지 않은 번호가 있습니다' }, '+ 이관 안 된 번호')] : null),
             h('td', null, (r.owner && r.owner.name) || '담당 미정'),
             h('td', { class: 'num' }, won(r.yday_spend)),
             h('td', { class: 'num' }, won(biz)),
             h('td', { class: 'num' }, open ? String(open) : '—'),
             h('td', null, STAGE[r.stage] || r.stage || ''));
  }
  function renderTable() {
    if (!state.board) return;   // 아직 못 불러옴 — 거르기·찾기를 눌러도 아무 일 없음
    var all = state.board.rows || [], rows = watchRows(), out = [];
    var grouped = state.me.scope === 'ALL' || state.me.scope === 'TEAM';
    if (grouped) {
      var teams = [], tAt = {};
      rows.forEach(function (r) {
        var t = r.owner.team_name || '담당 미정', p = r.owner.name || '담당 미정';
        if (!(t in tAt)) { tAt[t] = teams.length; teams.push({ name: t, people: [], pAt: {} }); }
        var T = teams[tAt[t]];
        if (!(p in T.pAt)) { T.pAt[p] = T.people.length; T.people.push({ name: p, rows: [] }); }
        T.people[T.pAt[p]].rows.push(r);
      });
      teams.forEach(function (T) {
        if (state.me.scope === 'ALL') out.push(h('tr', { class: 'grp team' }, h('td', { colspan: 9 }, h('b', null, T.name))));
        T.people.forEach(function (P) {
          var mine = P.rows;
          var cn = { red: 0, yellow: 0, white: 0, need: 0 };
          mine.forEach(function (r) { if (cn[r.verdict.color] !== undefined) cn[r.verdict.color]++; if (r.verdict.needs_attention) cn.need++; });
          out.push(h('tr', { class: 'grp' }, h('td', { colspan: 9 }, h('b', null, P.name), ' · ' + mine.length + '곳 · 확인 필요 ' + cn.need +
                                                                        ' · 🔴 ' + cn.red + ' · 🟡 ' + cn.yellow + ' · ⚪ ' + cn.white)));
          P.rows.forEach(function (r) { out.push(row(r)); });
        });
      });
    } else {
      rows.forEach(function (r) { out.push(row(r)); });
    }
    if (!out.length) {
      var msg = !all.length ? (stageInputMessage() || '현재 조회 범위에 표시할 광고주가 없습니다.')
        : state.filter === 'need' ? (resultsIncomplete() ? '현재 표시할 확인 필요 항목이 없습니다. 「전체」 또는 「점검 불가」에서 미점검 상태도 확인해 주세요.' : '현재 조회 범위에서 확인이 필요한 광고주가 없습니다.') : '조건에 맞는 광고주가 없습니다.';
      out.push(h('tr', null, h('td', { colspan: 9, class: 'empty' }, msg)));
    }
    put($('tbody'), out);
    var kind = { ALL: '전체', TEAM: '우리 팀', MINE: '내 담당' }[state.me.scope] || '';
    $('tbl-n').textContent = kind + (state.selection !== 'all' ? ' · 고른 범위' : '') + ' · ' + rows.length + ' / ' + all.length + '곳';
    Array.prototype.forEach.call(document.querySelectorAll('#tblChips .chip'), function (b) {
      b.classList.toggle('on', b.getAttribute('data-f') === state.filter);
    });
  }
  function setFilter(f) {
    state.filter = f;
    state.filterFromRoute = false;
    if (!state.board) return;
    renderIwan();
    renderKpis();
    renderWatchSelection();
  }

  // 이슈 손길
  function hand(i, act, body, btn) {
    once('issue:' + i.issue_id, btn, function () {
      return api('POST', '/issues/' + i.issue_id + '/' + act, body).then(function () {
        toast({ ack: '👀 확인 중으로 바꿨습니다(기록 남김)', resolve: '✅ 해결로 바꿨습니다 — 다음 점검에서 그대로면 다시 🆕', except: '🙈 예외로 두었습니다(기록 남김)' }[act]);
        reload();
      }, function (e) { toast(errText(e)); reload(); });
    });
  }
  /* 손길 뒤 다시 읽기 — 지금 보고 있는 화면이 관제·광고주 한 장일 때만(그 사이 다른 화면으로 옮겨 갔으면 건드리지 않는다 ·
     돌아오면 route 가 새로 읽는다) · 늦게 온 옛 응답이 새 것을 덮지 않게 세대를 올린다 */
  function reload() {
    var r = parse(location.pathname);
    if (r.screen === 'client') { state.gen++; openClient(r.id); }
    else if (r.screen === 'watch') { state.gen++; openWatch(); }
    else if (r.screen === 'dashboard') { state.gen++; openDashboard(); }
  }
  var except = null;
  /* 날짜는 서버의 「오늘」로 센다(브라우저 시계가 틀려도 한도가 어긋나지 않게) — 관제 판 band.today · 광고주 한 장 today. */
  function serverToday() {
    var r = parse(location.pathname);
    if (r.screen === 'client' && state.client && state.client.today) return state.client.today;
    return state.board && state.board.band ? state.board.band.today : null;
  }
  function addDays(iso, n) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return null;
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3] + n));
    return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0');
  }
  function askExcept(i, btn) {
    if (state.loadedDay && kstDay() !== state.loadedDay) {   // 자정이 지났다 — 서버의 오늘로 다시 받은 뒤에(검토 midnight)
      toast('날짜가 바뀌어 새로 불러왔습니다 — 다시 눌러 주세요');
      reload();
      return;
    }
    var today = serverToday(), max = i.can && i.can.except_until_max;
    if (!today || !max) { toast('지금은 예외를 줄 수 없습니다'); return; }
    except = i;
    $('mx-sub').textContent = (i.name || (state.client && state.client.name) || '') + ' — ' + cause(i.code);
    var opts = [1, 3, 7, 14, 30].filter(function (d) { var u = addDays(today, d - 1); return u !== null && u <= max; });
    put($('mx-days'), opts.map(function (d) {
      return h('option', { value: addDays(today, d - 1) }, (d === 1 ? '오늘까지' : d + '일(오늘 포함)') + ' · ' + md(addDays(today, d - 1)) + '까지');
    }));
    $('mx-rule').textContent = i.severity === 'red' ? '🔴 긴급 예외는 대표만 · 오늘 포함 최대 7일 · 기간이 끝나면 저절로 다시 봅니다' :
      '🟡 주의 · ⓘ 예외는 오늘 포함 최대 30일 · 기간이 끝나면 저절로 다시 봅니다';
    $('mx-why').value = '';
    openModal('m-except', btn);
    $('mx-why').focus();
  }
  function doExcept() {
    var i = except, note = $('mx-why').value.trim(), until = $('mx-days').value;
    if (!i) return;
    if (!note) { toast(ERR['note-required']); return; }
    closeModals();
    hand(i, 'except', { until: until, note: note });
  }

  // 🔗 짝 확인
  var PAIR = { auto: '자동 짝 — 계정 확인 전', candidate: '이름이 비슷한 계정', blocked: '자동으로 못 이음', superseded: '밀린 확인',
               missing: '오늘 이관 목록에 없음', broken: '🔌 이관 빠짐' };
  var BLOCK = { 'ad-account-id-format': '광고 계정 ID 숫자 확인 필요',
                'name-different': '번호는 일치하지만 계정 이름이 달라 별도 대조 필요',
                'ad-account-not-linked': '에이전시 목록에서 광고 계정을 찾지 못함',
                'account-identifiers-conflict': '광고 계정 ID와 기존 고객번호가 서로 다른 계정',
                'not-linked': '우리 회사로 이관 안 됨', 'ad-account-number': '고객 번호가 아닌 광고계정 번호가 적힘',
                'customer-id-format': '고객 번호 모양이 아님', 'customer-id-length': '고객 번호 자릿수가 아님',
                'ambiguous-space': '번호를 가를 수 없음', 'claimed-by-several': '여러 광고주에 같은 번호',
                'confirmed-elsewhere': '다른 광고주에 확인된 계정', 'name-points-elsewhere': '계정 이름이 다른 광고주를 가리킴' };
  function loadLinks() {
    var gen = state.gen, selection = state.selection, linkGen = ++state.linksGen;
    return api('GET', '/links/pending').then(function (j) {
      if (gen !== state.gen || selection !== state.selection || linkGen !== state.linksGen) return;
      state.links = j; renderLinks(); renderClientLinks();
    }, function (e) { if (gen === state.gen && selection === state.selection && linkGen === state.linksGen) fail(e); });
  }
  function linkRow(r, where) {
    var act = [], gen = state.gen, links = state.links;
    if (readOnly()) r = Object.assign({}, r, { can_confirm: verifiedLinking() && r.can_confirm === true, can_reject: false, confirm_blocked: false });
    var accountProof = null;
    if (r.can_confirm && verifiedLinking() && r.code !== 'same') {
      accountProof = h('input', { type: 'text', inputmode: 'numeric', maxlength: '15', autocomplete: 'off',
        placeholder: '원본 광고 계정 ID', 'aria-label': '원본 광고 계정 ID · ' + (r.name || '') });
      act.push(accountProof);
    }
    if (r.can_confirm === true) act.push(h('button', { type: 'button', class: 'btn sm blue', onclick: function (ev) {
      if (gen !== state.gen || links !== state.links) return;
      decide(r, 'confirm', ev.currentTarget, accountProof ? accountProof.value.trim() : null);
    } }, '이 계정 맞음'));
    else if (r.confirm_blocked) act.push(h('span', { class: 'blocked-note' }, '조직 자료가 낡아 「이 계정 맞음」은 잠시 막힘'));
    if (!readOnly() && (r.can_confirm || r.confirm_blocked)) act.push(h('button', { type: 'button', class: 'btn sm', onclick: function (ev) { preview(r, ev.currentTarget); } }, '캠페인 이름 보기'));
    if (r.can_reject) act.push(h('button', { type: 'button', class: 'btn sm', onclick: function (ev) { decide(r, 'reject', ev.currentTarget); } }, '아님'));
    var name = where === 'client' ? null : [h('button', { type: 'button', class: 'link', onclick: function () { go('/naver/clients/' + r.possibility_id); } }, r.name || ''), ' — '];
    return h('div', { class: 'line' },
             h('div', { class: 'tx' }, name, PAIR[r.state] || r.state,
               r.state === 'blocked' && r.code ? ' · ' + (BLOCK[r.code] || r.code) : '',
               h('span', { class: 'w' }, r.tail ? '고객 번호 ••••' + r.tail : '번호 없음',
                 r.account_name ? ' · 계정 이름 「' + r.account_name + '」' : '',
                 r.other_candidate ? ' · 다른 후보 있음' : '')),
             h('div', { class: 'act' }, act));
  }
  function decisionRow(d, where) {
    var name = where === 'client' ? null : [h('button', { type: 'button', class: 'link', onclick: function () { go('/naver/clients/' + d.possibility_id); } }, nameOf(d.possibility_id)), ' — '];
    return h('div', { class: 'line' },
             h('div', { class: 'tx' }, name, d.decision === 'confirmed' ? '사람 확인 「맞음」' : '사람 판단 「아님」',
               h('span', { class: 'w' }, '고객 번호 ••••' + (d.tail || '') + ' · ' + (d.decided_by || '') + ' ' + mdhm(d.decided_at))),
             h('div', { class: 'act' }, readOnly() ? null : h('button', { type: 'button', class: 'btn sm', onclick: function (ev) { askRevoke(d, ev.currentTarget); } }, '거두기')));
  }
  function nameOf(pid) {
    var rows = (state.board && state.board.rows) || [];
    for (var k = 0; k < rows.length; k++) if (rows[k].possibility_id === pid) return rows[k].name;
    var lr = (state.links && state.links.rows) || [];
    for (var j = 0; j < lr.length; j++) if (lr[j].possibility_id === pid) return lr[j].name;
    return '광고주';
  }
  function renderLinks() {
    if (!state.links) return;
    var L = state.links, box = $('linksBody');
    var auto = L.rows.filter(function (r) { return r.state === 'auto' && r.code === 'same' && r.can_confirm === true; });
    $('confirmAuto').hidden = !verifiedLinking() || !auto.length;
    $('confirmAuto').textContent = '이름·번호 일치 계정 연결 확정 (' + auto.length + '곳)';
    $('links-n').textContent = L.rows.length + '건';
    var out = [];
    if (!L.pairing_at) out.push(h('div', { class: 'empty' }, '아직 짝 맞추기를 받지 못했습니다.'));
    else if (!L.pairing_today) out.push(h('div', { class: 'note warn' }, '오늘 짝 맞추기 전입니다 — 어제 받은 목록입니다.'));
    L.rows.forEach(function (r) { out.push(linkRow(r)); });
    if (L.pairing_at && !L.rows.length) out.push(h('div', { class: 'empty' }, '확인할 짝이 없습니다.'));
    if ((L.decisions || []).length) {
      out.push(h('div', { class: 'cause' }, '사람이 내린 판단 ', h('span', { class: 'n' }, L.decisions.length + '건 · 거두면 다음 짝 맞추기부터 자동 규칙으로')));
      L.decisions.forEach(function (d) { out.push(decisionRow(d)); });
    }
    put(box, out);
    box.hidden = !state.linksOpen;
    $('linksToggle').textContent = state.linksOpen ? '접기' : '펼치기';
    $('linksToggle').setAttribute('aria-expanded', String(state.linksOpen));
  }
  function decide(r, act, btn, accountProof) {
    var gen = state.gen, links = state.links;
    if (!links || !(links.rows || []).some(function (current) {
      return current.ref === r.ref && (act === 'confirm' ? current.can_confirm === true : current.can_reject === true);
    })) return;
    once('link:' + r.ref, btn, function () {
      var body = { refs: [r.ref] };
      if (accountProof !== null && accountProof !== undefined) body.ad_account_no = accountProof;
      return api('POST', '/links/' + act, body).then(function () {
        if (gen !== state.gen || links !== state.links) return;
        toast(act === 'confirm' ? '「이 계정 맞음」으로 기록했습니다 — 다음 짝 맞추기부터 반영됩니다' : '「아님」으로 기록했습니다');
        state.links = null;
        loadLinks();
        reload();
      }, function (e) {
        if (gen !== state.gen || links !== state.links) return;
        // 짝 목록이 바뀌었을 수 있다(새 짝 맞추기 · 엔진 다시 켬) — 목록을 새로 받아 죽은 줄을 치운다
        toast(e.status === 404 ? '짝 목록이 바뀌었습니다 — 새로 불러왔으니 다시 확인해 주세요' : errText(e));
        if (e.status !== 401) { state.links = null; loadLinks(); }
      });
    });
  }
  function confirmAutomatic() {
    var rows = ((state.links && state.links.rows) || []).filter(function (r) { return r.state === 'auto' && r.code === 'same' && r.can_confirm === true; });
    var gen = state.gen, links = state.links;
    if (!verifiedLinking() || !rows.length) return;
    once('confirm-auto', $('confirmAuto'), function () {
      var count = 0;
      function next() {
        if (gen !== state.gen || links !== state.links) return Promise.resolve();
        var batch = rows.splice(0, 50);
        if (!batch.length) return Promise.resolve();
        return api('POST', '/links/confirm', { refs: batch.map(function (r) { return r.ref; }) }).then(function (j) {
          count += j.decided; return next();
        });
      }
      return next().then(function () { if (gen === state.gen && links === state.links) toast(count + '곳 연결을 확정했습니다. 「이관 현황」에서 관리·수집 결과를 확인해 주세요.'); },
        function (e) { if (gen === state.gen && links === state.links) toast(count + '곳 확정 후 중단했습니다 — ' + errText(e)); })
        .then(function () { if (gen === state.gen && links === state.links) loadLinks(); });
    });
  }
  var lastCollectionState = null;
  var collectionLabels = { accepted: '조회 접수됨 · 다음 처리 차례에 시작합니다', running: '조회 중',
    done: '조회 처리 완료', failed: '조회 실패', refused: '조회 보류', busy: '이미 조회 대기·실행 중',
    partial: '일부만 조회됨 · 미완료 계정 확인 필요', idle: '대기 중 · 요청 접수는 조회 완료가 아닙니다' };
  var collectionReasons = { RETRY_NOT_DUE: '재시도 간격 20분이 지나지 않았습니다',
    DAILY_LIMIT: '오늘 실행 한도에 도달했습니다', DONE_TODAY: '오늘 조회할 대상은 이미 처리했습니다',
    ORG_STALE: '조직 자료 갱신이 필요합니다', NO_SCOPE: '대표 권한을 다시 확인해 주세요',
    COLLECTION_TIME_BUDGET: '조회 시간 한도에 도달했습니다', COLLECTION_FAILED: '조회 오류를 점검해 주세요',
    COLLECTION_BUSY: '기존 요청을 처리 중입니다', PROCESS_RESTARTED_NOT_REPLAYED: '서버 재시작으로 이전 요청은 다시 실행하지 않았습니다' };
  function showCollection(j) {
    var parts = [collectionLabels[j.status] || '조회 상태 확인 필요'];
    var counts = j.counts || {};
    if (counts.targets !== undefined) parts.push('대상 ' + counts.targets + ' · 완료 ' + (counts.ok || 0) + ' · 미완료 ' + Math.max(0, counts.targets - (counts.ok || 0)));
    (j.codes || []).forEach(function (c) { parts.push(collectionReasons[c] || ('사유: ' + c)); });
    $('collectionStatus').textContent = parts.join(' · ');
    $('collectNow').disabled = j.status === 'accepted' || j.status === 'running' || j.status === 'busy';
    var previous = lastCollectionState;
    lastCollectionState = j.status;
    if ((previous === 'accepted' || previous === 'running') && ['done', 'partial', 'failed', 'refused'].indexOf(j.status) >= 0) reload();
  }
  function loadCollection() {
    if (!fullCollectionAllowed()) return Promise.resolve();
    return api('GET', '/collection/status').then(showCollection, function (e) {
      if (e.status !== 401) $('collectionStatus').textContent = '조회 상태를 확인하지 못했습니다 — ' + errText(e);
    });
  }
  function requestCollection() {
    if (!fullCollectionAllowed() || state.busy.collection) return;
    state.busy.collection = true;
    $('collectNow').disabled = true;
    api('POST', '/collection/request', {}).then(showCollection, function (e) {
      if (e.body && e.body.status) showCollection(e.body); else fail(e);
    }).then(function () {
      delete state.busy.collection;
      $('collectNow').disabled = ['accepted', 'running', 'busy'].indexOf(lastCollectionState) >= 0;
    });
  }
  function preview(r, btn) {
    once('preview:' + r.ref, btn, function () {
      return api('POST', '/links/preview', { ref: r.ref }).then(function (j) {
        var names = j.campaigns || [];
        toast(names.length ? '캠페인: ' + names.join(' · ') : '캠페인이 없습니다');
      }, function (e) { toast(errText(e)); });
    });
  }
  var revoke = null;
  function askRevoke(d, btn) { revoke = d; $('mr-why').value = ''; openModal('m-revoke', btn); $('mr-why').focus(); }
  function doRevoke() {
    var d = revoke, why = $('mr-why').value.trim();
    if (!d) return;
    if (!why) { toast(ERR['note-required']); return; }
    closeModals();
    once('revoke:' + d.decision_id, null, function () {
      return api('POST', '/links/revoke', { decision_id: d.decision_id, reason: why }).then(function () {
        toast('판단을 거두었습니다');
        state.links = null;
        loadLinks();
      }, function (e) {
        toast(errText(e));
        if (e.status !== 401) { state.links = null; loadLinks(); }
      });
    });
  }

  // 📦 계약 끝난 광고주
  function loadEnded() {
    return api('GET', '/ended').then(function (j) { state.ended = j; renderEnded(); }, fail);
  }
  function renderEnded() {
    var E = state.ended, box = $('endedBody');
    if (!E) return;
    $('ended-n').textContent = E.rows.length + '곳';
    var tbl = h('div', { class: 'tblwrap' }, h('table', null,
      h('thead', null, h('tr', null, ['광고주', '담당', '계약 끝난 날', '지난 날', '이관', '점검'].map(function (t) { return h('th', null, t); }))),
      h('tbody', null, E.rows.length ? E.rows.map(function (r) {
        return h('tr', { class: 'click', onclick: function () { go('/naver/clients/' + r.possibility_id); } },
                 h('td', null, h('button', { type: 'button', class: 'link' }, r.name || '')),
                 h('td', null, (r.owner && r.owner.name) || '담당 미정'),
                 h('td', { class: 'num' }, r.end_date ? md(r.end_date) : '모름'),
                 h('td', { class: 'num' }, typeof r.days_since_end === 'number' ? r.days_since_end + '일' : '—'),
                 h('td', null, r.still_linked ? h('span', { class: 'pill p-amber' }, '이관 남음 — 네이버에서 해제 권장') : h('span', { class: 'pill p-gray' }, '해제됨')),
                 h('td', null, r.checks_stopped ? '점검 멈춤' : '점검 중(끝난 지 14일 안)'));
      }) : h('tr', null, h('td', { colspan: 6, class: 'empty' }, '계약 끝난 광고주가 없습니다.')))));
    put(box, h('p', { class: 'hint pad' }, '계약이 끝날 때까지 쌓아 둔 기록과 하루 한 번 받는 대행 연결 목록에서 본 이관 여부뿐입니다(그 광고주 계정에 따로 들어가지 않음). 재계약되면 저절로 다시 매일 점검 대상이 됩니다.'), tbl);
    box.hidden = !state.endedOpen;
    $('endedToggle').textContent = state.endedOpen ? '접기' : '펼치기';
    $('endedToggle').setAttribute('aria-expanded', String(state.endedOpen));
  }

  // ── 광고주 한 장 ───────────────────────────────────────────────────
  function openClient(id) {
    var gen = state.gen;
    show('client');
    if (String(state.clientId) !== String(id)) {
      // 다른 광고주로 — 앞 광고주의 이름·칸·단추가 남아 눌리지 않게 먼저 비운다(검토 client-switch-stale)
      state.client = null;
      $('c-crumb').textContent = '';
      $('c-name').textContent = '';
      $('c-sub').textContent = '';
      $('c-sig').className = 'sig white';
      put($('c-badges'));
      ['p-hist', 'p-rep', 'p-conn'].forEach(function (p) { put($(p)); });
      put($('p-now'), h('div', { class: 'loading' }, '불러오는 중…'));
      setCtab('now');
    }
    state.clientId = id;
    api('GET', '/clients/' + id).then(function (c) {
      if (gen !== state.gen) return;
      state.client = c;
      state.loadedDay = kstDay();
      renderClient();
      if (!state.links) loadLinks(); else renderClientLinks();
    }, function (e) {
      if (e.status === 401) return;
      if (gen !== state.gen) return;
      state.client = null;
      $('c-name').textContent = '없거나 볼 수 없는 광고주입니다';
      $('c-crumb').textContent = '';
      $('c-sub').textContent = '';
      $('c-sig').className = 'sig white';
      put($('c-badges'));
      ['p-now', 'p-hist', 'p-rep', 'p-conn'].forEach(function (p) { put($(p)); });
      put($('p-now'), h('div', { class: 'empty' }, errText(e)));
      setCtab('now');
    });
  }
  function renderClient() {
    var c = state.client, v = c.verdict;
    $('c-crumb').textContent = c.name;
    $('c-name').textContent = c.name;
    $('c-sig').className = 'sig ' + v.color;
    $('c-sub').textContent = '담당 ' + ((c.owner && c.owner.name) || '담당 미정') + (c.owner && c.owner.team_name ? ' · ' + c.owner.team_name : '') +
      ' · 계약 단계 ' + (STAGE[c.stage] || c.stage || '') + (c.managed ? '' : ' · 관리 목록 밖');
    var lk = LINK[c.link] || LINK.none;
    var vc = { red: 'p-red', yellow: 'p-amber', green: 'p-green', white: 'p-gray' }[v.color];
    put($('c-badges'), h('span', { class: 'pill ' + vc }, v.color === 'white' ? '점검 불가 · ' + statusText(v) : COLOR_TEXT[v.color]),
        v.needs_attention ? h('span', { class: 'needdot' }, '확인 필요') : null,
        h('span', { class: 'pill ' + lk[0] }, lk[1]),
        c.unlinked && c.link !== 'not_linked' ? h('span', { class: 'pill p-gray' }, '+ 이관 안 된 번호') : null,
        c.account_unconfirmed ? h('span', { class: 'pill p-gray' }, '계정 확인 전') : null,
        REL[c.relation] ? h('span', { class: 'pill p-blue' }, REL[c.relation]) : null);
    renderNow();
    renderHist();
    put($('p-rep'), h('div', { class: 'auto-soon' }, h('b', null, '4차에 엽니다.'), ' 이 광고주의 주간·월간 보고서가 여기에 쌓입니다. 「계정 확인 전」이면 만들지 않습니다.'));
    renderConn();
    setCtab(state.ctab);
  }
  function setCtab(t) {
    state.ctab = t;
    Array.prototype.forEach.call(document.querySelectorAll('[data-ctab]'), function (b) {
      var on = b.getAttribute('data-ctab') === t;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
    });
    ['now', 'hist', 'rep', 'conn'].forEach(function (p) { $('p-' + p).classList.toggle('on', p === t); });
  }
  /* 타일 · 14일 막대는 서버가 센 값 그대로(모든 계정을 읽었을 때만 합 · 일부만 읽은 날은 흐리게) — 화면이 계정별 기록을
     다시 더하지 않는다(검토 client-tiles-summed-in-browser) */
  function renderNow() {
    var c = state.client;
    var days = c.days || [];
    var read = c.yday_spend !== null && c.yday_spend !== undefined;
    var out = [];
    if (!c.accounts || !c.accounts.length) {
      out.push(h('div', { class: 'note warn' }, '이 광고주에 이어진 네이버 계정이 없습니다(' + (LINK[c.link] || LINK.none)[1] + '). 「연결」 칸에서 짝을 확인합니다.'));
    } else if (!read) {
      out.push(h('div', { class: 'note ' + (c.link === 'broken' ? 'bad' : 'warn') }, '오늘 점검에서 모든 계정의 숫자를 읽지 못했습니다' +
        (c.verdict.color === 'white' ? '(' + statusText(c.verdict) + ')' : '') + ' — 일부만 더한 값은 보이지 않습니다. 「연결」 칸에서 이관 상태를 봅니다.'));
    }
    if (c.accounts && c.accounts.length) {
      out.push(h('div', { class: 'tiles' },
        tile('어제 광고비', won(c.yday_spend), '오늘 점검 기준'), tile('노출', num(c.yday_imp), '어제'),
        tile('클릭', num(c.yday_clk), '어제'), tile('비즈머니', won(c.bizmoney), '오늘 점검 시 잔액')));
      var max = 0, any = false;
      days.forEach(function (d) { if (d.yday_spend !== null) { any = true; if (d.yday_spend > max) max = d.yday_spend; } });
      out.push(h('div', { class: 'kh' }, h('h2', null, '최근 14일 광고비'), h('span', { class: 'n' }, any ? '막대 = 그날 아침 점검이 읽은 전날 광고비 · 흐린 막대 = 그날 일부 계정만 읽음 · 빈 막대 = 기록 없음' : '아침 점검 기록이 쌓이면 막대로 보입니다')));
      var bars = h('div', { class: 'sbars', 'aria-hidden': 'true' });
      days.forEach(function (d) {
        var s = d.yday_spend;
        var bar = h('i', { class: s === null ? 'none' : d.complete ? '' : 'part',
                           title: md(d.day) + ' 점검 · ' + won(s) + (s !== null && !d.complete ? ' · 일부 계정만' : '') });
        bar.style.height = (s === null || !max ? 3 : Math.max(3, Math.round(s / max * 100))) + '%';
        bars.appendChild(bar);
      });
      if (any) out.push(bars);
    }
    put($('p-now'), h('div', { class: 'card' }, out),
        h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '열린 이슈'), h('span', { class: 'n' }, '여기서 바로 👀 · ✅ · 🙈')),
          openOf(c).length ? openOf(c).map(function (i) { return issueRow(i, 'client'); }) : h('div', { class: 'empty' }, '열린 이슈가 없습니다.')));
  }
  function openOf(c) { return (c.issues || []).filter(function (i) { return i.state_now === 'new' || i.state_now === 'ack'; }); }
  function tile(l, v, d) { return h('div', { class: 'tile' }, h('div', { class: 'l' }, l), h('div', { class: 'v' }, v), h('div', { class: 'd' }, d)); }
  function renderHist() {
    var c = state.client, items = [];
    (c.issues || []).forEach(function (i) {
      (i.events || []).forEach(function (e) {
        items.push({ at: e.at, i: i, e: e });
      });
    });
    items.sort(function (a, b) { return a.at < b.at ? 1 : a.at > b.at ? -1 : 0; });
    var KIND = { opened: '새로 생김', reappeared: '다시 생김', escalated: '등급 올라감', deescalated: '등급 내려감',
                 exception_ended: '예외 기간 끝남', auto_resolved: '🔁 저절로 풀림', closed_unlinked: '짝이 사라져 닫힘',
                 acked: '👀 확인 중', resolved: '✅ 해결', excepted: '🙈 예외' };
    put($('p-hist'), h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '이슈 기록'), h('span', { class: 'n' }, '누가 · 언제 · 무엇을 · 예외 사유 — 최근 14일과 열린 이슈')),
      items.length ? h('ul', { class: 'tl' }, items.map(function (x) {
        var sev = x.e.severity === 'red' ? 'red' : x.e.severity === 'yellow' ? 'yellow' : 'info';
        return h('li', null, h('span', { class: 't' }, mdhm(x.e.at)),
                 h('span', null, h('span', { class: 'sig ' + sev }), cause(x.i.code) + ' — ' + (KIND[x.e.kind] || x.e.kind) +
                   (x.e.by ? ' · ' + x.e.by : '') + (x.e.exception_until ? ' · ' + md(x.e.exception_until) + '까지' : ''),
                   x.e.note ? h('span', { class: 'hint' }, ' 📝 ' + x.e.note) : null));
      })) : h('div', { class: 'empty' }, '기록이 없습니다.')));
  }
  var CONN = {
    listed: '이 광고주 광고계정이 우리 회사 대행 연결 목록에 있습니다. 매일 아침 목록을 전부 받아 확인하고, 빠지면 「🔌 이관 빠짐」으로 알립니다.',
    missing: '오늘 받은 대행 연결 목록에 없습니다(첫날). 목록이 하루 잘려 온 것일 수 있어 오늘은 ⚪ 로만 보입니다. 내일 점검에도 없으면 「🔌 이관 빠짐」(🔴)으로 올립니다.',
    broken: '대행 연결 목록에 없습니다(서로 다른 날 두 번 · 20시간 넘게). ① 광고주에게 네이버 검색광고 「대행사 관리」에서 메타아이앤씨 연결이 남아 있는지 확인 요청 ② 광고주가 직접 끊은 것이면 전산 계약 단계 확인 ③ 다시 이관되면 다음 날 아침 🔁 저절로 풀립니다.',
    not_linked: '전산에 네이버 고객 번호는 적혀 있는데 우리 회사 대행 연결 목록에 한 번도 없습니다 — 아직 이관되지 않았습니다(⚪). 매주 월요일 담당에게 「이관 받을 곳」 목록으로 알립니다.',
    none: '이어진 네이버 계정이 없습니다. 전산 광고주 관리에 네이버 고객 번호가 적혀 있는지, 아래 짝 확인 줄이 있는지 봅니다.',
    pending: '오늘 짝 맞추기 전입니다. 받은 뒤에 이관 상태가 보입니다.'
  };
  function renderConn() {
    var c = state.client, lk = LINK[c.link] || LINK.none;
    put($('p-conn'),
        h('div', { class: 'card' }, h('div', { class: 'kh' }, h('h2', null, '🔌 이관'), h('span', { class: 'pill ' + lk[0] }, lk[1]),
          h('span', { class: 'n' }, '대행 연결 목록 기준 · 이관 = 광고주 광고계정이 우리 회사에 연결된 상태')),
          h('p', { class: 'sub' }, CONN[c.link] || CONN.none)),
        h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '이어진 계정'), h('span', { class: 'n' }, '고객 번호는 끝 4자리만 보입니다')),
          (c.accounts || []).length ? c.accounts.map(function (a) {
            return h('div', { class: 'line' }, h('div', { class: 'tx' }, h('span', { class: 'masked' }, '•••• ' + (a.tail || '')),
              a.account_name ? ' · 「' + a.account_name + '」' : '',
              h('span', { class: 'w' }, a.link === 'confirmed' ? '사람이 확인한 짝' : '전산 고침 번호로 이어진 자동 짝 — 계정 확인 전', ' · ', PAIR[a.state] || (a.state === 'confirmed' ? '확인됨' : a.state))));
          }) : h('div', { class: 'empty' }, '없습니다.')),
        h('div', { class: 'card flat', id: 'c-links' }, h('div', { class: 'kh' }, h('h2', null, '🔗 이 광고주 짝 확인')), h('div', { class: 'loading' }, '불러오는 중…')));
    renderClientLinks();
  }
  function renderClientLinks() {
    var box = $('c-links');
    if (!box || !state.client || !state.links) return;
    var pid = state.client.possibility_id;
    var rows = state.links.rows.filter(function (r) { return r.possibility_id === pid; });
    var dec = (state.links.decisions || []).filter(function (d) { return d.possibility_id === pid; });
    var list = rows.map(function (r) { return linkRow(r, 'client'); }).concat(dec.map(function (d) { return decisionRow(d, 'client'); }));
    put(box, h('div', { class: 'kh' }, h('h2', null, '🔗 이 광고주 짝 확인'), h('span', { class: 'n' }, readOnly() ?
      '연결 확정 뒤에도 광고 변경·자동입찰·보고서 전송은 켜지지 않습니다' : '「이 계정 맞음」을 누르면 자동화·광고주 보고서가 켜질 수 있습니다')),
        list.length ? list : h('div', { class: 'empty' }, '확인할 짝이 없습니다.'));
  }

  // ── 🔔 ───────────────────────────────────────────────────────────
  function openBell() {
    var gen = ++state.bellGen;
    state.bell = null;
    $('bellAll').disabled = true;   // 목록을 받기 전에는 「모두 읽음」을 누를 수 없다(검토 bell-read-all-before-load)
    $('shade').classList.add('on');
    $('drawer').classList.add('on');
    $('drawer').setAttribute('aria-hidden', 'false');
    put($('drawerBody'), h('div', { class: 'loading' }, '불러오는 중…'));
    $('drawerX').focus();
    api('GET', '/bell').then(function (j) {
      if (gen !== state.bellGen) return;
      state.bell = j;
      renderBell();
      setBell(j.unread);
      $('bellAll').disabled = false;
    }, fail);
  }
  function closeBell() {
    var was = $('drawer').classList.contains('on');
    state.bellGen++;
    $('shade').classList.remove('on');
    $('drawer').classList.remove('on');
    $('drawer').setAttribute('aria-hidden', 'true');
    if (was && !$('top').hidden) $('bell').focus();
  }
  function renderBell() {
    var items = state.bell.items || [];
    put($('drawerBody'), items.length ? items.map(function (it) {
      return h('button', { type: 'button', class: 'bitem' + (it.read ? '' : ' unread'), onclick: function () { bellOpen(it); } },
               h('span', { class: 'sig ' + (it.severity === 'URGENT' ? 'red' : 'yellow') }), h('b', null, it.title || '알림'),
               (it.lines || []).map(function (l) { return h('span', { class: 'w' }, l); }),
               h('span', { class: 'w' }, md(it.day) + (it.read ? ' · 읽음' : '') + (it.status === 'held' ? ' · 비서방에 보내지 않고 남겨 둠' : '')));
    }) : h('div', { class: 'empty' }, '최근 14일 알림이 없습니다.'));
  }
  function bellOpen(it) {
    if (!state.bell) return;
    var next = typeof it.link === 'string' && SCREEN.test(it.link) ? it.link : null;
    var done = function () { closeBell(); if (next) go(next); };
    if (it.read || readOnly()) return done();
    api('POST', '/bell/' + it.recipient_id + '/read').then(function () {
      it.read = true;
      setBell(Math.max(0, (state.bell.unread || 1) - 1));
      state.bell.unread = Math.max(0, (state.bell.unread || 1) - 1);
      done();
    }, function (e) { toast(errText(e)); });
  }
  function bellAll() {
    if (!state.bell) return;
    once('bell-all', $('bellAll'), function () {
      return api('POST', '/bell/read-all').then(function () {
        if (!state.bell) return;
        (state.bell.items || []).forEach(function (i) { i.read = true; });
        state.bell.unread = 0;
        setBell(0);
        renderBell();
      }, function (e) { toast(errText(e)); });
    });
  }

  // ── ⚙️ 설정 ───────────────────────────────────────────────────────
  var TH = {
    bizmoney_red_days: ['비즈머니 🔴 긴급', '남은 날(잔액 ÷ 최근 7일 하루 평균 광고비)이 이보다 적으면', '일'],
    bizmoney_yellow_days: ['비즈머니 🟡 주의', '남은 날이 이보다 적으면', '일'],
    jump_up_ratio: ['광고비 급증', '같은 요일 4주 평균의 이 배 이상이면', '배'],
    jump_down_ratio: ['광고비 급감', '같은 요일 4주 평균의 이 배 이하면', '배'],
    jump_min_spend: ['급변 제외 작은 광고비', '기준과 어제가 둘 다 이보다 작으면 급변을 보지 않음', '원'],
    jump_min_weeks: ['급변 기준에 필요한 주', '같은 요일 4주 중 이만큼은 자료가 있어야', '주'],
    stage_stale_hours: ['전산 단계 자료 낡음', '이보다 오래되면 단계·광고비 규칙을 돌리지 않음', '시간'],
    zero_spend_days: ['진행중인데 광고비 0원', '최근 이 날수 합계가 0원이면 🟡', '일'],
    period_end_days: ['캠페인 기간 곧 끝남', '이 날수 안에 끝나면 ⓘ', '일']
  };
  var HOLD = { org: '조직(사람·팀)', stages: '계약 단계', accounts: '대행 연결 목록' };
  function openSettings() {
    var gen = state.gen;
    show('settings');
    if (!(state.me.scope === 'ALL' || state.me.scope === 'TEAM')) {
      $('set-ps').textContent = ERR['settings-denied'] + ' — 점검 기준은 대표님이 정합니다.';
      ['th', 'time', 'ppl', 'sys'].forEach(function (p) { put($('sp-' + p)); });
      return;
    }
    Promise.all([api('GET', '/settings'), api('GET', '/health')]).then(function (a) {
      if (gen !== state.gen) return;
      state.settings = a[0];
      state.health = a[1];
      renderSettings();
    }, fail);
  }
  function renderSettings() {
    var s = state.settings, ceo = !!s.can_edit && !readOnly();
    $('set-ps').textContent = readOnly() ? '읽기 전용 검증판에서는 점검 기준을 변경할 수 없습니다.' : '매일 열지 않는 것만 모았습니다. ' + (ceo ? '점검 기준은 대표님이 고칩니다(고친 기록이 남습니다).' : '팀장은 보기만 합니다 — 점검 기준은 대표님이 고칩니다.');
    var th = s.thresholds || {}, rg = s.ranges || {};
    var inputs = {};
    var rows = Object.keys(TH).map(function (k) {
      var inp = ceo ? h('input', { class: 'thin', type: 'number', step: 'any', id: 'th-' + k, value: th[k], min: rg[k] ? rg[k][0] : null, max: rg[k] ? rg[k][1] : null, 'aria-label': TH[k][0] }) : null;
      inputs[k] = inp;
      // 값 칸을 앞에 — 좁은 화면(390px)에서도 옆으로 밀지 않고 고칠 수 있게(검토 settings-390)
      return h('tr', null, h('td', null, h('b', null, TH[k][0])), h('td', { class: 'num' }, inp || String(th[k])),
               h('td', null, TH[k][2]), h('td', { class: 'wrap' }, TH[k][1]),
               h('td', { class: 'num hint' }, rg[k] ? rg[k][0] + ' ~ ' + rg[k][1] : ''));
    });
    var save = ceo ? h('div', { class: 'line' }, h('div', { class: 'tx' }, '바꾼 칸만 보냅니다 · 범위 밖 값은 저장되지 않습니다 · 다음 아침 점검부터 씁니다'),
      h('div', { class: 'act' }, h('button', { type: 'button', class: 'btn blue', onclick: function (ev) { saveTh(inputs, ev.currentTarget); } }, '기준 저장'))) : null;
    var hist = (s.history || []).slice(0, 10).map(function (x) {
      var ch = Object.keys(x.after || {}).filter(function (k) { return (x.before || {})[k] !== x.after[k]; });
      return h('li', null, h('span', { class: 't' }, mdhm(x.at)), h('span', null, (x.by || '') + ' · ' + ch.map(function (k) { return (TH[k] ? TH[k][0] : k) + ' ' + x.before[k] + ' → ' + x.after[k]; }).join(' · ')));
    });
    put($('sp-th'), h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '점검 기준'), h('span', { class: 'n' }, '처음 4주는 이 값으로 운영하고 맞춥니다')),
      ceo ? null : h('div', { class: 'line' }, h('span', { class: 'ro' }, readOnly() ? '읽기 전용 검증판 — 변경할 수 없습니다' : '보기만 — 대표님만 고칩니다')),
      h('div', { class: 'tblwrap' }, h('table', null, h('thead', null, h('tr', null, ['점검', '값', '단위', '문제로 보는 기준', '허용 범위'].map(function (t) { return h('th', null, t); }))), h('tbody', null, rows))), save),
      h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '고친 기록'), h('span', { class: 'n' }, '최근 10번')), hist.length ? h('ul', { class: 'tl' }, hist) : h('div', { class: 'empty' }, '아직 고친 적이 없습니다.')));
    put($('sp-time'), h('div', { class: 'card' }, h('div', { class: 'kh' }, h('h2', null, '점검 시각 · 알림')),
      h('p', { class: 'sub' }, readOnly() ? '아침 점검 예정 시각은 06:30, 마감은 ' + (s.deadline || '08:00') + '입니다. 현재 시간대에는 아직 수집·점검 전일 수 있습니다. 미점검은 정상 판정이 아니며 자료 기준 시각을 확인해 주세요.' : '아침 점검은 06:30 에 시작해 ' + (s.deadline || '08:00') + ' 까지 끝납니다. 그때까지 못 끝낸 광고주는 「오늘 점검 안 됨」(⚪)으로 보이고 🟢 로 보이지 않습니다.'),
      h('p', { class: 'sub' }, readOnly() ? '이 검증판의 알림 전송·자동입찰은 꺼져 있습니다. 알림 목록은 저장된 기록만 조회하며 읽음 처리도 하지 않습니다.' : '알림은 전산 비서방으로 갑니다(휴대폰 알림 없음). 처음 2주는 그림자 운영 — 이슈는 만들되 광고주 알림은 대표님께만 요약으로 갑니다. 🟡 는 12시간 안 풀리면 한 단계 위로 올라갑니다.')));
    var me = state.me;
    put($('sp-ppl'), h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '사람 · 팀'), h('span', { class: 'n' }, '전산에서 받은 조직(읽기 전용) · 보는 범위 안만')),
      h('div', { class: 'tblwrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '사람'), h('th', null, '팀'), h('th', null, '재직'))),
        h('tbody', null, (me.people || []).map(function (p) {
          var t = (me.teams || []).filter(function (x) { return x.idx === p.team_idx; })[0];
          return h('tr', null, h('td', null, p.name || ''), h('td', null, t ? t.name : '—'), h('td', null, p.active ? '재직' : '퇴사·정지'));
        }))))));
    renderSys();
    setSpane(state.spane);
  }
  function renderSys() {
    var s = state.settings, hl = state.health || {}, out = [];
    var runs = hl.runs || [];
    out.push(h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '오늘 점검 회차'), h('span', { class: 'n' }, '조직 자료 ' + ({ fresh: '맑음', yellow: '조금 늦음', stale: '낡음', none: '없음' }[hl.org_freshness] || '—') + ' · 짝 맞추기 ' + (hl.pairing_today ? '오늘 받음' : '오늘 전'))),
      runs.length ? h('ul', { class: 'tl' }, runs.map(function (r) {
        return h('li', null, h('span', { class: 't' }, hm(r.started_at) + (r.finished_at ? '~' + hm(r.finished_at) : '')),
                 h('span', null, { running: '도는 중', done: '끝', failed: '실패' }[r.status] || r.status,
                   typeof r.accounts_total === 'number' ? ' · 계정 ' + num(r.accounts_ok) + ' / ' + num(r.accounts_total) : '',
                   r.error_kind ? ' · ' + r.error_kind : ''));
      })) : h('div', { class: 'empty' }, '오늘 회차가 아직 없습니다.')));
    if (s.holds) {
      out.push(h('div', { class: 'card flat' }, h('div', { class: 'kh' }, h('h2', null, '대표님 확인이 필요한 목록'), h('span', { class: 'n' }, '목록이 한꺼번에 크게 바뀌어 받지 않고 붙잡아 두었습니다 · 3시간 안에 확인')),
        s.holds.length ? s.holds.map(function (x) {
          return h('div', { class: 'line' }, h('div', { class: 'tx' }, h('b', null, HOLD[x.kind] || x.kind), h('span', { class: 'w' }, mdhm(x.at) + ' 붙잡음 · ' + (x.codes || []).join(' · '))),
                   h('div', { class: 'act' }, readOnly() ? null : h('button', { type: 'button', class: 'btn blue sm', onclick: function (ev) { confirmHold(x, ev.currentTarget); } }, '대표 확인하고 받기')));
        }) : h('div', { class: 'empty' }, '붙잡아 둔 목록이 없습니다.')));
    }
    put($('sp-sys'), out);
  }
  function setSpane(p) {
    state.spane = p;
    Array.prototype.forEach.call(document.querySelectorAll('[data-sp]'), function (b) { b.classList.toggle('on', b.getAttribute('data-sp') === p); });
    ['th', 'time', 'ppl', 'sys'].forEach(function (x) { $('sp-' + x).classList.toggle('on', x === p); });
  }
  function saveTh(inputs, btn) {
    var cur = state.settings.thresholds || {}, changes = {}, bad = false;
    Object.keys(inputs).forEach(function (k) {
      var el = inputs[k];
      if (!el) return;
      var v = el.value === '' ? NaN : Number(el.value);
      if (!isFinite(v)) { bad = true; return; }
      if (v !== cur[k]) changes[k] = v;
    });
    if (bad) { toast('숫자를 넣어 주세요'); return; }
    if (!Object.keys(changes).length) { toast(ERR['no-change']); return; }
    once('th', btn, function () {
      return api('POST', '/settings/thresholds', { changes: changes }).then(function () { toast('점검 기준을 저장했습니다 — 다음 아침 점검부터'); state.gen++; openSettings(); },
        function (e) { toast(e.body && e.body.fields && e.body.fields.length ? '범위 밖이거나 맞지 않는 값: ' + e.body.fields.map(function (k) { return TH[k] ? TH[k][0] : k; }).join(' · ') : errText(e)); });
    });
  }
  function confirmHold(x, btn) {
    once('hold:' + x.kind, btn, function () {
      return api('POST', '/holds/' + x.kind + '/confirm', { hold_id: x.hold_id }).then(function () { toast('확인하고 받았습니다'); state.gen++; openSettings(); },
        function (e) { toast(errText(e)); state.gen++; openSettings(); });
    });
  }

  // ── 창 ───────────────────────────────────────────────────────────
  function openModal(id, from) {
    state.lastFocus = from || document.activeElement;
    $(id).classList.add('on');
  }
  function closeModals() {
    var open = document.querySelector('.modal.on');
    Array.prototype.forEach.call(document.querySelectorAll('.modal'), function (m) { m.classList.remove('on'); });
    except = null;
    revoke = null;
    managementEdit = null;
    reportEdit = null;
    var back = state.lastFocus;
    state.lastFocus = null;
    if (open && back && document.body.contains(back) && !back.disabled) back.focus();
  }
  /* 창 · 🔔 서랍 안에서만 Tab 이 돈다 */
  function trapTab(ev) {
    var box = document.querySelector('.modal.on .box') || ($('drawer').classList.contains('on') ? $('drawer') : null);
    if (!box || ev.key !== 'Tab') return;
    var f = Array.prototype.filter.call(box.querySelectorAll('button, input, select, textarea, [tabindex]:not([tabindex="-1"])'),
      function (el) { return !el.disabled && el.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    else if (!box.contains(document.activeElement)) { ev.preventDefault(); first.focus(); }
  }
  /* 탭 줄에서 ← → 로 옮겨 가기 */
  function arrowTabs(sel, attr, pick) {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(sel));
    tabs.forEach(function (b, n) {
      b.addEventListener('keydown', function (ev) {
        if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
        ev.preventDefault();
        var next = tabs[(n + (ev.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        pick(next.getAttribute(attr));
        next.focus();
      });
    });
  }

  // ── 고정 단추 ────────────────────────────────────────────────────
  function bind() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-go]'), function (b) {
      b.addEventListener('click', function () { go(b.getAttribute('data-go')); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('#tblChips .chip'), function (b) {
      b.addEventListener('click', function () { setFilter(b.getAttribute('data-f')); });
    });
    $('q').addEventListener('input', function () { state.q = this.value.trim(); renderWatchSelection(); });
    $('inventorySearch').addEventListener('input', function () { state.inventoryQ = this.value.trim(); renderInventory(); });
    $('inventoryView').addEventListener('change', function () { state.inventoryView = this.value; loadInventory(); });
    $('inventoryMapping').addEventListener('change', function () { state.inventoryMapping = this.value; loadInventory(); });
    $('inventoryWorkflow').addEventListener('change', function () { state.inventoryWorkflow = this.value; loadInventory(); });
    $('inventoryReload').addEventListener('click', loadInventory);
    $('managementSave').addEventListener('click', saveManagement);
    $('reportsReload').addEventListener('click', loadReports);
    $('reviewSave').addEventListener('click', saveReportReview);
    $('dashboardReload').addEventListener('click', function () { state.gen++; openDashboard(); });
    $('collectNow').addEventListener('click', requestCollection);
    $('confirmAuto').addEventListener('click', confirmAutomatic);
    $('scope').addEventListener('change', function () { state.selection = this.value; route(); });
    $('doneToggle').addEventListener('click', function () { if (state.board) { state.doneOpen = !state.doneOpen; renderIssues(); } });
    $('linksToggle').addEventListener('click', function () {
      state.linksOpen = !state.linksOpen;
      if (state.linksOpen && !state.links) loadLinks(); else renderLinks();
      if (!state.linksOpen) { $('linksBody').hidden = true; $('linksToggle').textContent = '펼치기'; $('linksToggle').setAttribute('aria-expanded', 'false'); }
    });
    $('endedToggle').addEventListener('click', function () {
      state.endedOpen = !state.endedOpen;
      if (state.endedOpen && !state.ended) loadEnded(); else renderEnded();
      if (!state.endedOpen) { $('endedBody').hidden = true; $('endedToggle').textContent = '펼치기'; $('endedToggle').setAttribute('aria-expanded', 'false'); }
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-ctab]'), function (b) {
      b.addEventListener('click', function () { setCtab(b.getAttribute('data-ctab')); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-sp]'), function (b) {
      b.addEventListener('click', function () { state.spaneFromRoute = false; setSpane(b.getAttribute('data-sp')); });
    });
    arrowTabs('[data-ctab]', 'data-ctab', setCtab);
    // 사람이 손대는 것만 센다(오래 쉬면 로그인을 끝낸다) — 마우스를 스치는 것은 세지 않는다
    ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(function (t) {
      document.addEventListener(t, function () { state.lastInput = Date.now(); }, { capture: true, passive: true });
    });
    $('bell').addEventListener('click', openBell);
    $('drawerX').addEventListener('click', closeBell);
    $('shade').addEventListener('click', closeBell);
    $('bellAll').addEventListener('click', bellAll);
    $('mx-ok').addEventListener('click', doExcept);
    $('mr-ok').addEventListener('click', doRevoke);
    Array.prototype.forEach.call(document.querySelectorAll('[data-close]'), function (b) { b.addEventListener('click', closeModals); });
    Array.prototype.forEach.call(document.querySelectorAll('.modal'), function (m) {
      m.addEventListener('click', function (ev) { if (ev.target === m) closeModals(); });
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { closeModals(); closeBell(); return; }
      trapTab(ev);
    });
  }

  // ── 시작 ─────────────────────────────────────────────────────────
  function loginFailed(e) {
    if (e && e.entryCode) return blocked('down', e.entryCode);
    var code = (e && e.body && e.body.error) || '';
    if (e.status === 401) return blocked('rejected', 'NV-S03');
    if (e.status === 403) return blocked('noscope', 'NV-S04');
    if (e.status === 429) return blocked('busy', 'NV-S05');
    if (code === 'bad-body' || e.status === 400) return blocked('rejected', 'NV-S03');
    return blocked('down', entryServerDiagnostic(e));
  }
  function boot() {
    scheduleRefresh();
    api('GET', '/me').then(function (me) {
      state.me = me;
      renderTop();
      route();
    }, function (e) { if (e.status !== 401) blocked('down', entryServerDiagnostic(e)); });
  }
  function start() {
    var entry = window.__metaincSso;
    bind();
    if (entry && (entry.started || entry.legacyPresent)) {
      dropSession();
      if (!entry.started || entry.legacyPresent) return blocked('login');
      return entry.consume().then(function (payload) {
        return api('POST', '/session', payload);
      }).then(function (j) { saveSession(j); boot(); }, loginFailed);
    }
    state.session = loadSession();
    if (!state.session) return blocked('login');
    boot();
  }
  start();
})();
