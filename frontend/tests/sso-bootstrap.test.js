const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { test } = require('node:test');

const file = path.join(__dirname, '../js/sso-bootstrap.js');
function page(query, options = {}) {
    const events = [], listeners = {}, timers = [];
    const opener = { postMessage: (body, origin) => events.push({ kind: 'message', body, origin }) };
    const location = new URL('https://logic.metainc.co.kr/' + query);
    const context = {
        URL, URLSearchParams, Promise, Uint8Array, TextEncoder, crypto: webcrypto,
        btoa: value => Buffer.from(value, 'binary').toString('base64'),
        document: { referrer: options.referrer === undefined ? 'https://metainc.co.kr/' : options.referrer, title: '로직' },
        location, opener: options.noOpener ? null : opener,
        history: { replaceState: (a, b, url) => { events.push({ kind: 'clean', url }); } },
        addEventListener: (type, fn) => { listeners[type] = fn; },
        removeEventListener: (type) => { delete listeners[type]; },
        setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {},
    };
    context.window = context;
    context.top = context;
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
    return { context, events, listeners, timers, opener };
}

test('주소를 먼저 비우고 PKCE를 부모 창과 1회 교환한다', async () => {
    const p = page('?sso_start=' + 'R'.repeat(43) + '&tab=keep#home');
    assert.equal(p.events[0].kind, 'clean');
    assert.equal(p.events[0].url, '/?tab=keep#home');
    const pending = p.context.__metaincSso.consume();
    await new Promise(resolve => setImmediate(resolve));
    const ready = p.events.find(x => x.kind === 'message');
    assert.equal(ready.body.type, 'METAINC_SSO_READY');
    assert.equal(ready.origin, 'https://metainc.co.kr');
    assert.match(ready.body.codeChallenge, /^[A-Za-z0-9_-]{43}$/);
    assert.equal(ready.body.codeVerifier, undefined);
    p.listeners.message({ source: p.opener, origin: ready.origin,
        data: { type: 'METAINC_SSO_CODE', requestId: 'R'.repeat(43), code: 'C'.repeat(43) } });
    const result = await pending;
    assert.equal(result.code, 'C'.repeat(43));
    assert.match(result.codeVerifier, /^[A-Za-z0-9_-]{43}$/);
    const challenge = Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(result.codeVerifier))).toString('base64url');
    assert.equal(ready.body.codeChallenge, challenge);
    assert.equal(p.context.opener, null);
    await assert.rejects(p.context.__metaincSso.consume());
});

test('직접 코드 URL·혼합 방식·중복 요청 식별자는 정리 후 거부한다', async () => {
    for (const query of ['?code=' + 'C'.repeat(43), '?sso_start=' + 'R'.repeat(43) + '&sso=old',
        '?sso_start=' + 'R'.repeat(43) + '&sso_start=' + 'R'.repeat(43), '?sso_start=short']) {
        const p = page(query);
        assert.equal(p.events[0].kind, 'clean');
        assert.equal(p.events[0].url, '/');
        await assert.rejects(p.context.__metaincSso.consume());
        assert.equal(p.events.filter(x => x.kind === 'message').length, 0);
        assert.equal(p.context.__metaincSso.takeLegacyToken(), '');
    }
});

test('허용 전산 출처·부모 창 없는 탐색은 거부한다', async () => {
    for (const options of [{ referrer: '' }, { referrer: 'https://metainc.co.kr.evil.example/' },
        { referrer: 'https://evil.example/' }, { noOpener: true }]) {
        const p = page('?sso_start=' + 'R'.repeat(43), options);
        await assert.rejects(p.context.__metaincSso.consume());
        assert.equal(p.events.filter(x => x.kind === 'message').length, 0);
    }
});

test('다른 창·출처·요청 식별자의 응답은 무시하고 60초 뒤 실패한다', async () => {
    const p = page('?sso_start=' + 'R'.repeat(43));
    const result = p.context.__metaincSso.consume();
    await new Promise(resolve => setImmediate(resolve));
    const message = { type: 'METAINC_SSO_CODE', requestId: 'R'.repeat(43), code: 'C'.repeat(43) };
    p.listeners.message({ source: {}, origin: 'https://metainc.co.kr', data: message });
    p.listeners.message({ source: p.opener, origin: 'https://evil.example', data: message });
    p.listeners.message({ source: p.opener, origin: 'https://metainc.co.kr', data: { ...message, requestId: 'X'.repeat(43) } });
    assert.equal(p.context.opener, p.opener);
    p.timers[0]();
    await assert.rejects(result);
    assert.equal(p.context.opener, null);
});

test('옛 토큰은 주소에서 즉시 제거하고 RAM에서 한 번만 꺼낸다', () => {
    const p = page('?sso=legacy-test-token&tab=keep');
    assert.equal(p.context.__metaincSso.started, false);
    assert.equal(p.context.__metaincSso.legacyPresent, true);
    assert.equal(p.events[0].url, '/?tab=keep');
    assert.equal(p.context.__metaincSso.takeLegacyToken(), 'legacy-test-token');
    assert.equal(p.context.__metaincSso.takeLegacyToken(), '');
    assert.equal(p.events.filter(x => x.kind === 'message').length, 0);
});

test('출처가 맞아도 코드 형식이 틀리면 세션 재시도 없이 실패한다', async () => {
    const p = page('?sso_start=' + 'R'.repeat(43));
    const pending = p.context.__metaincSso.consume();
    await new Promise(resolve => setImmediate(resolve));
    p.listeners.message({ source: p.opener, origin: 'https://metainc.co.kr',
        data: { type: 'METAINC_SSO_CODE', requestId: 'R'.repeat(43), code: 'bad' } });
    await assert.rejects(pending);
    assert.equal(p.context.opener, null);
});

test('두 HTML의 첫 inline 수신부가 공용 원문과 동일하다', () => {
    const source = fs.readFileSync(file, 'utf8').trim();
    for (const name of ['index.html', 'index.bundle.html']) {
        const html = fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
        const first = html.match(/<script[^>]*>([\s\S]*?)<\/script>/);
        assert.ok(first, name);
        assert.equal(first[1].trim(), source, name);
        assert.ok(html.indexOf('<meta name="referrer" content="no-referrer">') < first.index);
        assert.ok(first.index < html.indexOf('rel="preconnect"'));
    }
});
