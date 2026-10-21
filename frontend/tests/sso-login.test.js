const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const code = Buffer.alloc(32, 18).toString('base64url');
const codeVerifier = Buffer.alloc(32, 52).toString('base64url');

function login(bootstrap, response = { ok: false, json: async () => ({ detail: '실패' }) }) {
    const source = fs.readFileSync(path.join(__dirname, '../js/components/App.jsx'), 'utf8');
    const effect = source.match(/useEffect\(function\(\) \{([\s\S]*?)\n    \}, \[\]\);/)[1];
    const requests = [], states = {}, storage = new Map([['logic_token', 'other-session'], ['logic_user', '{}']]);
    const context = {
        window: { __metaincSso: bootstrap, location: { search: '' } },
        sessionStorage: { getItem: k => storage.get(k), removeItem: k => storage.delete(k) },
        fetch: async (url, options) => { requests.push({ url, options }); return response; },
        setCurrentUser: v => { states.user = v; }, setAuthToken: v => { states.token = v; },
        setAuthChecking: v => { states.checking = v; }, saveAuth: (u, t) => { states.saved = { u, t }; },
        URLSearchParams, JSON, Promise, AbortController, setTimeout, clearTimeout,
    };
    vm.runInNewContext('(function(){' + effect + '})()', context);
    return { requests, states, storage };
}

test('새 교환이 실패하면 다른 기존 세션을 복원하지 않는다', async () => {
    const result = login({ started: true, consume: () => Promise.resolve({ code, codeVerifier }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(result.requests.map(x => x.url), ['/api/auth/sso-code']);
    assert.equal(result.storage.has('logic_token'), false);
    assert.equal(result.states.saved, undefined);
    assert.equal(result.states.checking, false);
});

test('유효한 새 교환은 자체 세션만 저장하고 코드·검증값은 저장하지 않는다', async () => {
    const data = { success: true, token: 'new-local-token', user: { id: 1, username: 'employee-test' } };
    const result = login({ started: true, consume: () => Promise.resolve({ code, codeVerifier }) },
        { ok: true, json: async () => data });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(result.requests.length, 1);
    assert.equal(result.requests[0].options.credentials, 'omit');
    assert.equal(result.requests[0].options.redirect, 'error');
    assert.equal(result.states.saved.t, 'new-local-token');
    assert.equal(result.states.saved.u.username, 'employee-test');
    assert.equal(result.storage.size, 0);
});

test('수신부 거부는 구 토큰 요청이나 기존 세션 조회로 바뀌지 않는다', async () => {
    const result = login({ started: true, consume: () => Promise.reject(new Error('실패')), takeLegacyToken: () => 'must-not-use' });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(result.requests.length, 0);
    assert.equal(result.storage.size, 0);
    assert.equal(result.states.checking, false);
});

test('구 토큰만 받은 경우에는 기존 SSO 엔드포인트를 유지한다', async () => {
    const result = login({ started: false, takeLegacyToken: () => 'legacy-test-token' },
        { ok: true, json: async () => ({ success: true, token: 'legacy-local', user: { id: 1 } }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(result.requests.map(x => x.url), ['/api/auth/sso']);
    assert.equal(JSON.parse(result.requests[0].options.body).token, 'legacy-test-token');
    assert.equal(result.states.saved.t, 'legacy-local');
});

test('SSO가 없는 일반 진입은 기존 세션 복원을 유지한다', async () => {
    const result = login({ started: false, takeLegacyToken: () => '' }, { ok: true, json: async () => ({ id: 1 }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(result.requests.map(x => x.url), ['/api/auth/me']);
    assert.equal(result.states.token, 'other-session');
});
