/* 실제 수신부와 앱을 함께 실행한다. DOM·시간·HTTP만 대체하며 브라우저/서버/외부 접속은 사용하지 않는다. */
'use strict';
const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const test = require('node:test');
const vm = require('node:vm');

const page = path.join(__dirname, '../backend/naver_page');
const bootstrap = fs.readFileSync(path.join(page, 'sso-bootstrap.js'), 'utf8');
const app = fs.readFileSync(path.join(page, 'app.js'), 'utf8');
const reports = fs.readFileSync(path.join(page, 'report-ui.js'), 'utf8');
const html = fs.readFileSync(path.join(page, 'index.html'), 'utf8');
const requestId = 'R'.repeat(43);
const code = 'C'.repeat(43);
const secretMarker = 'SYNTHETIC_DO_NOT_DISPLAY';

class Element {
  constructor() {
    this.textContent = '';
    this.children = [];
    this.attrs = {};
    const classes = new Set();
    this.classList = {
      add: value => classes.add(value),
      remove: value => classes.delete(value),
      contains: value => classes.has(value),
      toggle: (value, on) => on ? classes.add(value) : classes.delete(value)
    };
  }
  addEventListener() {}
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  appendChild(child) { return this.insertBefore(child, null); }
  insertBefore(child, before) {
    if (child === before) return child;
    if (child.parentNode) child.parentNode.removeChild(child);
    const index = before === null ? this.children.length : this.children.indexOf(before);
    assert.ok(index >= 0);
    this.children.splice(index, 0, child); child.parentNode = this; return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child); assert.ok(index >= 0);
    this.children.splice(index, 1); child.parentNode = null; return child;
  }
  get childNodes() { return this.children; }
  get firstChild() { return this.children[0]; }
}

function launch(options = {}) {
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element()]));
  function findDynamic(root, id) {
    if (root.attrs && root.attrs.id === id) return root;
    for (const child of root.children || []) { const found = findDynamic(child, id); if (found) return found; }
    return null;
  }
  const events = new Map();
  const timers = new Map();
  const intervals = new Map();
  const storage = new Map(Object.entries(options.storage || {}));
  const requests = [];
  const messages = [];
  const trace = [];
  let timerId = 0;
  let now = Date.now();
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const location = new URL(options.url || `https://watch.invalid/naver/reports?sso_start=${requestId}`);
  const parent = {
    postMessage(data, origin) {
      trace.push('ready');
      messages.push({ data, origin });
      if (options.postMessageFailure) throw new Error(secretMarker);
    }
  };
  const window = {
    location,
    opener: options.opener === false ? null : parent,
    crypto: options.crypto || webcrypto,
    addEventListener: (name, callback) => events.set(name, callback),
    removeEventListener: (name, callback) => { if (events.get(name) === callback) events.delete(name); }
  };
  window.top = options.iframe ? {} : window;
  const history = {
    replaceState(_, title, value) {
      trace.push('clean-url');
      if (options.historyFailure) throw new Error(secretMarker);
      location.href = new URL(value, location).href;
    }
  };
  window.history = history;
  const document = {
    visibilityState: 'visible',
    title: '네이버 관제',
    referrer: options.referrer === undefined ? 'https://metainc.co.kr/ad-studio' : options.referrer,
    getElementById: id => elements.get(id) || [...elements.values()].map(el => findDynamic(el, id)).find(Boolean) || null,
    querySelectorAll: () => [],
    querySelector: () => null,
    createElement: () => new Element(),
    createTextNode: text => ({ textContent: text }),
    addEventListener() {}
  };
  const context = vm.createContext({
    window, document, location, history, URL, URLSearchParams, TextEncoder, Uint8Array, AbortController, performance, Date: ClockDate,
    btoa: text => Buffer.from(text, 'binary').toString('base64'),
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay, next: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
    setInterval: (fn, delay) => { const id = ++timerId; intervals.set(id, { fn, delay, next: now + delay }); return id; },
    clearInterval: id => intervals.delete(id),
    fetch: async (url, init) => {
      trace.push('fetch');
      requests.push({ url, init });
      if (options.networkFailure) throw new Error(secretMarker);
      const runtime = url === '/api/naver-auto/health?runtime=1';
      if (runtime) {
        assert.equal(init.method, 'GET');
        assert.ok(init.signal instanceof AbortSignal);
      }
      const response = runtime ? { status:200, body:{runtime:{state:'unavailable', indicator:'red',
        reason_code:'UNAVAILABLE', verified_at:null, valid_for_seconds:0, retry_at:null}} } : url.endsWith('/session') ? (options.session || {
        status: 200, body: { token: 'synthetic-session-token', expires_in: 3600 }
      }) : url.endsWith('/session/refresh') ? (options.refresh ? options.refresh() : {
        status: 200, body: { token: 'synthetic-refreshed-token', expires_in: 3600 }
      }) : url.includes('/reports/accounts?') ? { status: 200, body: { selection: 'all', rows: [], page: 0, total: 0, next_page: null,
        period: {kind:'weekly',start:'2026-09-21',end:'2026-09-27'}, schedule:{} } } :
        (options.me || { status: 200, body: { scope: 'MINE', name: '합성 직원' } });
      return { status: response.status, ok: response.status >= 200 && response.status < 300,
        json: async () => response.body };
    }
  });
  vm.runInContext(bootstrap, context, { filename: 'sso-bootstrap.js' });
  vm.runInContext(reports, context, { filename: 'report-ui.js' });
  vm.runInContext(app, context, { filename: 'app.js' });
  return {
    window, location, storage, requests, messages, trace, elements, events, timers,
    advance: async milliseconds => {
      const end = now + milliseconds;
      while (intervals.size || timers.size) {
        const next = Math.min(...[...intervals.values(), ...timers.values()].map(timer => timer.next));
        if (next > end) break;
        now = next;
        for (const timer of [...intervals.values()]) {
          if (timer.next === next) { timer.next += timer.delay; timer.fn(); }
        }
        for (const [id, timer] of [...timers]) {
          if (timer.next === next) { timers.delete(id); timer.fn(); }
        }
        await new Promise(resolve => setImmediate(resolve));
      }
      now = end;
    },
    text: () => ['b-t', 'b-p'].map(id => elements.get(id).textContent).join('\n'),
    message: overrides => {
      const receive = events.get('message');
      if (receive) receive(Object.assign({ source: parent, origin: 'https://metainc.co.kr',
        data: { type: 'METAINC_SSO_CODE', requestId, code } }, overrides));
    },
    timeout: () => {
      for (const timer of [...timers.values()]) if (timer.delay === 60000) timer.fn();
    }
  };
}

async function until(predicate, timeoutMs = 1000) {
  // 반복 횟수는 경과 시간이 아니다. 실제 작업 완료를 확인하며 타이머에 양보하고, 단조 시계로 제한한다.
  const deadline = performance.now() + timeoutMs;
  while (!predicate()) {
    const remaining = deadline - performance.now();
    assert.ok(remaining > 0, '합성 실행 조건이 제한 시간 안에 완료되지 않았습니다.');
    await new Promise(resolve => setTimeout(resolve, Math.min(5, remaining)));
  }
}

async function blocked(run) {
  await until(() => run.elements.get('s-blocked').classList.contains('on'));
  return run.text();
}

test('암호화 작업이 늦게 완료되어도 실제 준비 메시지와 화면 완료까지 기다린다', async () => {
  let digestCompleted = false;
  const run = launch({ crypto: {
    getRandomValues: array => webcrypto.getRandomValues(array),
    subtle: { digest: async (...args) => {
      await new Promise(resolve => setTimeout(resolve, 30));
      const result = await webcrypto.subtle.digest(...args);
      digestCompleted = true;
      return result;
    } }
  } });
  await until(() => run.messages.length);
  assert.equal(digestCompleted, true);
  assert.equal(run.messages[0].data.type, 'METAINC_SSO_READY');
  run.message();
  await until(() => run.elements.get('s-reports').classList.contains('on'));
  assert.deepEqual(run.requests.map(request => request.url), ['/api/naver-auto/session', '/api/naver-auto/me',
    '/api/naver-auto/health?runtime=1', '/api/naver-auto/reports/accounts?selection=all&kind=weekly&page=0&view_sync=1']);
});

test('암호화가 끝나지 않으면 대기 제한 시간에 실패하며 무한히 기다리지 않는다', { timeout: 1000 }, async () => {
  const run = launch({ crypto: {
    getRandomValues: array => webcrypto.getRandomValues(array),
    subtle: { digest: () => new Promise(() => {}) }
  } });
  const started = performance.now();
  await assert.rejects(until(() => run.messages.length, 20), /제한 시간 안에 완료되지 않았습니다/);
  assert.ok(performance.now() - started >= 20);
  assert.equal(run.messages.length, 0);
  assert.equal(run.requests.length, 0);
  run.timeout();
  assert.match(await blocked(run), /진단 코드: NV-E06/);
});

test('referrer가 없어도 허용된 전산 창의 출처·요청·PKCE 확인 뒤 로그인한다', async () => {
  const run = launch({ referrer: '' });
  await until(() => run.messages.length === 4);
  assert.deepEqual(run.messages.map(message => message.origin), [
    'https://metainc.co.kr', 'http://metainc.co.kr', 'https://www.metainc.co.kr', 'http://www.metainc.co.kr'
  ]);
  run.message();
  await until(() => run.elements.get('s-reports').classList.contains('on'));
  const payload = JSON.parse(run.requests[0].init.body);
  const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(payload.codeVerifier));
  assert.equal(Buffer.from(digest).toString('base64url'), run.messages[0].data.codeChallenge);
  assert.equal(run.requests.filter(request => request.url === '/api/naver-auto/session').length, 1);
  assert.equal(run.window.opener, null);
});

test('수신부 실패 사유를 구분해 안내하되 모든 경우 인증 교환을 차단한다', async t => {
  const scenarios = [
    ['잘못된 요청', { url: 'https://watch.invalid/naver/?sso_start=invalid' }, 'NV-E01'],
    ['중복 요청', { url: `https://watch.invalid/naver/?sso_start=${requestId}&sso_start=${requestId}` }, 'NV-E01'],
    ['주소의 코드', { url: `https://watch.invalid/naver/?code=${code}` }, 'NV-E01'],
    ['허용하지 않은 출처', { referrer: `https://untrusted.invalid/${secretMarker}` }, 'NV-E03'],
    ['해석할 수 없는 출처', { referrer: secretMarker }, 'NV-E03'],
    ['새 창 연결 없음', { opener: false }, 'NV-E04'],
    ['referrer와 새 창 연결 모두 없음', { referrer: '', opener: false }, 'NV-E04'],
    ['내장 창', { iframe: true }, 'NV-E05'],
    ['referrer 없는 내장 창', { referrer: '', iframe: true }, 'NV-E05'],
    ['응답 만료', {}, 'NV-E06', async run => { await until(() => run.messages.length); run.timeout(); }],
    ['암호화 기능 없음', { crypto: {} }, 'NV-E07'],
    ['암호화 실패', { crypto: { getRandomValues: array => array.fill(1), subtle: {
      digest: () => Promise.reject(new Error(secretMarker))
    } } }, 'NV-E07'],
    ['주소 정리 실패', { historyFailure: true }, 'NV-E08'],
    ['창 통신 실패', { postMessageFailure: true }, 'NV-E09'],
    ['잘못된 수신 코드', {}, 'NV-E01', async run => {
      await until(() => run.messages.length);
      run.message({ data: { type: 'METAINC_SSO_CODE', requestId, code: secretMarker } });
    }]
  ];
  for (const [name, options, diagnostic, act] of scenarios) {
    await t.test(name, async () => {
      const run = launch(options);
      if (act) await act(run);
      const text = await blocked(run);
      assert.ok(text.includes('진단 코드: ' + diagnostic), text);
      assert.match(text, /광고 스튜디오 › 네이버 관제/);
      assert.doesNotMatch(text, /SYNTHETIC_DO_NOT_DISPLAY|https?:\/\/|R{43}|C{43}|Error:|\.js:\d/);
      assert.equal(run.requests.length, 0);
      assert.equal(run.storage.size, 0);
      assert.equal(run.window.opener, null);
      assert.equal(run.events.has('message'), false);
      assert.equal(run.timers.size, 0);
    });
  }
});

test('로그인 교환 실패와 로그인 후 조직 자료 실패를 고정 안내로 구분한다', async t => {
  const scenarios = [
    ['전산 응답 없음', { session: { status: 503, body: { error: 'erp-unavailable' } } }, 'NV-S01', /전산 로그인 서버/],
    ['전산 응답 형식', { session: { status: 503, body: { error: 'erp-bad-shape' } } }, 'NV-S02', /응답 형식/],
    ['인증 거절', { session: { status: 401, body: { error: 'sso-rejected' } } }, 'NV-S03', /전산 로그인/],
    ['권한 거절', { session: { status: 403, body: { error: 'no-scope' } } }, 'NV-S04', /관제 대상/],
    ['요청 제한', { session: { status: 429, body: { error: 'too-many-logins' } } }, 'NV-S05', /1분/],
    ['잘못된 본문', { session: { status: 400, body: { error: 'bad-body' } } }, 'NV-S03', /전산 로그인/],
    ['네트워크 실패', { networkFailure: true }, 'NV-S06', /네트워크/],
    ['관제 엔진 연결', { session: { status: 503, body: { error: 'engine-unavailable' } } }, 'NV-S07', /관제 서버/],
    ['관제 엔진 지연', { session: { status: 504, body: { error: 'engine-timeout' } } }, 'NV-S08', /답변이 늦어/],
    ['조직 자료 낡음', { me: { status: 503, body: { error: 'org-stale' } } }, 'NV-M01', /조직 자료.*오래/],
    ['교환 시 조직 자료 없음', { session: { status: 503, body: { error: 'org-unavailable' } } }, 'NV-M01', /조직 자료.*없/],
    ['로그인 후 조직 자료 없음', { me: { status: 503, body: { error: 'org-unavailable' } } }, 'NV-M01', /조직 자료.*없/],
    ['알 수 없는 응답', { session: { status: 500, body: { error: secretMarker, message: secretMarker } } }, 'NV-S00', /완료하지 못했습니다/],
    ['상속 속성 이름', { session: { status: 500, body: { error: '__proto__', message: secretMarker } } }, 'NV-S00', /완료하지 못했습니다/]
  ];
  for (const [name, options, diagnostic, message] of scenarios) {
    await t.test(name, async () => {
      const run = launch(options);
      await until(() => run.messages.length);
      run.message();
      const text = await blocked(run);
      assert.ok(text.includes('진단 코드: ' + diagnostic), text);
      assert.match(text, message);
      assert.match(text, /광고 스튜디오 › 네이버 관제/);
      assert.doesNotMatch(text, /SYNTHETIC_DO_NOT_DISPLAY|synthetic-session-token|https?:\/\/|R{43}|C{43}|Error:/);
      assert.deepEqual(run.requests.map(request => request.url), options.me
        ? ['/api/naver-auto/session', '/api/naver-auto/me'] : ['/api/naver-auto/session']);
    });
  }
});

test('허용 출처의 정상 로그인은 실제 PKCE와 한 번의 교환을 거쳐 기존 직원 화면을 연다', async t => {
  for (const origin of ['https://metainc.co.kr', 'http://metainc.co.kr', 'https://www.metainc.co.kr', 'http://www.metainc.co.kr']) {
    await t.test(origin, async () => {
      const run = launch({ referrer: origin + '/ad-studio' });
      await until(() => run.messages.length);
      assert.equal(run.messages[0].origin, origin);
      run.message({ origin });
      await until(() => run.elements.get('s-reports').classList.contains('on'));
      const sessionRequest = run.requests[0];
      const payload = JSON.parse(sessionRequest.init.body);
      assert.equal(payload.code, code);
      assert.match(payload.codeVerifier, /^[A-Za-z0-9_-]{43}$/);
      const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(payload.codeVerifier));
      assert.equal(Buffer.from(digest).toString('base64url'), run.messages[0].data.codeChallenge);
      assert.deepEqual(run.trace, ['clean-url', 'ready', 'fetch', 'fetch', 'fetch', 'fetch']);
      assert.equal(run.location.search, '');
      assert.deepEqual(run.requests.map(request => request.url), ['/api/naver-auto/session', '/api/naver-auto/me',
        '/api/naver-auto/health?runtime=1', '/api/naver-auto/reports/accounts?selection=all&kind=weekly&page=0&view_sync=1']);
      assert.deepEqual(run.requests.map(request => request.init.method), ['POST', 'GET', 'GET', 'GET']);
      assert.equal(run.requests[1].init.headers.Authorization, 'Bearer synthetic-session-token');
      for (const request of run.requests) {
        assert.equal(request.init.credentials, 'omit');
        assert.equal(request.init.referrerPolicy, 'no-referrer');
        assert.equal(request.init.redirect, 'error');
      }
      assert.equal(run.window.opener, null);
      assert.equal(run.events.has('message'), false);
      assert.equal(run.timers.size, 0);
      assert.equal(run.storage.size, 1);
      const saved = run.storage.get('naverWatch.session');
      assert.doesNotMatch(saved, /R{43}|C{43}|codeVerifier|codeChallenge/);
      assert.ok(!saved.includes(payload.codeVerifier));
      await assert.rejects(run.window.__metaincSso.consume(), /이미 사용한/);
      run.message({ origin });
      assert.equal(run.requests.length, 4);
      assert.equal(run.requests.filter(request => request.url === '/api/naver-auto/session').length, 1);
    });
  }
});

test('출처·보낸 창·요청 번호가 다른 메시지는 무시하고 기존 1분 제한 뒤 차단한다', async t => {
  const forgeries = [
    ['다른 출처', { origin: 'https://untrusted.invalid' }],
    ['허용 목록이어도 기존 referrer와 다른 출처', { origin: 'https://www.metainc.co.kr' }],
    ['다른 창', { source: {} }],
    ['다른 요청', { data: { type: 'METAINC_SSO_CODE', requestId: 'X'.repeat(43), code } }],
    ['다른 유형', { data: { type: 'OTHER', requestId, code } }]
  ];
  for (const [name, message] of forgeries) {
    await t.test(name, async () => {
      const run = launch();
      await until(() => run.messages.length);
      run.message(message);
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(run.requests.length, 0);
      assert.equal(run.elements.get('s-blocked').classList.contains('on'), false);
      run.timeout();
      assert.match(await blocked(run), /진단 코드: NV-E06/);
      run.message();
      assert.equal(run.requests.length, 0);
    });
  }
});

test('referrer 없이도 위조 출처·다른 창·다른 요청은 인증 교환에 도달하지 않는다', async t => {
  for (const overrides of [
    {origin:'null'}, {origin:'https://metainc.co.kr.untrusted.invalid'}, {source:{}},
    {data:{type:'METAINC_SSO_CODE',requestId:'X'.repeat(43),code}}
  ]) {
    await t.test(JSON.stringify(overrides), async () => {
      const run = launch({referrer:''});
      await until(() => run.messages.length === 4);
      run.message(overrides);
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(run.requests.length, 0);
      run.timeout();
      assert.match(await blocked(run), /NV-E06/);
    });
  }
});

test('새 진입 실패는 이 창의 이전 세션을 지우고 직접 주소·구형 토큰은 허용하지 않는다', async t => {
  for (const query of ['', '?sso=' + secretMarker, `?sso_start=${requestId}&sso=${secretMarker}`]) {
    await t.test(query || '직접 주소', async () => {
      const run = launch({ url: 'https://watch.invalid/naver/' + query });
      assert.match(await blocked(run), /전산에서 들어와 주세요/);
      assert.equal(run.requests.length, 0);
      assert.equal(run.location.search, '');
    });
  }
  const run = launch({ referrer: 'https://untrusted.invalid', storage: {
    'naverWatch.session': JSON.stringify({ token: 'synthetic-old-token', exp: Date.now() + 3600000 })
  } });
  assert.match(await blocked(run), /NV-E03/);
  assert.equal(run.storage.size, 0);
  assert.equal(run.requests.length, 0);
});

test('저장 세션의 조직 자료 오류에도 진단을 표시하고 401 세션 종료 처리는 유지한다', async t => {
  for (const [status, error, message] of [[503, 'org-stale', /진단 코드: NV-M01/], [503, 'org-unavailable', /진단 코드: NV-M01/], [401, 'token-expired', /다시 들어와 주세요/]]) {
    await t.test(String(status), async () => {
      const run = launch({ url: 'https://watch.invalid/naver/reports', storage: {
        'naverWatch.session': JSON.stringify({ token: 'synthetic-old-token', exp: Date.now() + 3600000 })
      }, me: { status, body: { error } } });
      assert.match(await blocked(run), message);
      assert.deepEqual(run.requests.map(request => request.url), ['/api/naver-auto/me']);
      assert.equal(run.storage.size, status === 401 ? 0 : 1);
    });
  }
});

test('모니터링 세션은 무활동 4시간 전까지 갱신하고 4시간에는 종료한다', async () => {
  const run = launch();
  await until(() => run.messages.length);
  run.message();
  await until(() => run.elements.get('s-reports').classList.contains('on'));
  await run.advance(239 * 60000);
  assert.equal(run.elements.get('s-reports').classList.contains('on'), true);
  assert.ok(run.storage.has('naverWatch.session'));
  await run.advance(60000);
  assert.match(await blocked(run), /오래 쉬어/);
  assert.equal(run.storage.size, 0);
});

test('갱신이 반복 실패해도 1분마다 다시 확인하여 토큰 만료 전에 복구한다', async () => {
  let calls = 0;
  const run = launch({ refresh: () => ++calls <= 5 ? { status: 503, body: { error: 'engine-timeout' } } :
    { status: 200, body: { token: 'synthetic-recovered-token', expires_in: 3600 } } });
  await until(() => run.messages.length);
  run.message();
  await until(() => run.elements.get('s-reports').classList.contains('on'));
  await run.advance(56 * 60000);
  assert.equal(calls, 6);
  assert.equal(JSON.parse(run.storage.get('naverWatch.session')).token, 'synthetic-recovered-token');
  await run.advance(5 * 60000);
  assert.equal(run.elements.get('s-reports').classList.contains('on'), true);
});

test('갱신 인증 거절은 계속 재시도하지 않고 세션을 종료한다', async () => {
  let calls = 0;
  const run = launch({refresh: () => {calls++; return {status:401,body:{error:'token-expired'}};}});
  await until(() => run.messages.length); run.message();
  await until(() => run.elements.get('s-reports').classList.contains('on'));
  await run.advance(55 * 60000);
  assert.equal(calls, 1);
  assert.equal(run.storage.size, 0);
  assert.match(await blocked(run), /다시 들어와 주세요/);
});
