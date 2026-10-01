// Offline diagnostic delivery checks. Real source, fake Chrome/network/time only.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
const popupSource = fs.readFileSync(path.join(__dirname, '../popup.js'), 'utf8');

function grab(name) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert(start >= 0, 'Missing ' + name);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('Unclosed ' + name);
}

function worker(options = {}) {
  const calls = [], logs = [], timers = new Map();
  let sequence = 0, listener;
  const chrome = {
    runtime: { getManifest: () => ({ version: '1.28.2' }),
      onMessage: { addListener: fn => { listener = fn; } } },
    tabs: { query: options.query || (async () => [{ id: 2, active: true }]) },
    scripting: { executeScript: options.inject || (async () => [{ result: { href: 'https://search.shopping.naver.com/search/all', tap: 'none' } }]) },
  };
  const context = vm.createContext({
    chrome, AbortController, RT: options.remote,
    CFG: { serverBase: 'https://server.invalid' },
    getToken: async () => options.token === undefined ? 'SENTINEL_PRIVATE_TOKEN' : options.token,
    fetch: async (url, init) => {
      calls.push({ url, init });
      return options.fetch ? options.fetch(url, init) : { ok: true, status: 200, json: async () => ({ success: true }) };
    },
    setTimeout: (fn, ms) => { const id = ++sequence; timers.set(id, { fn, ms }); return id; },
    clearTimeout: id => timers.delete(id),
    log: async value => logs.push(value),
  });
  vm.runInContext(['reportBlocked', 'tapReport', 'navProbe'].map(grab).join('\n'), context);
  vm.runInContext(source.slice(source.indexOf('chrome.runtime.onMessage.addListener(')), context);
  return { context, chrome, calls, logs, timers,
    message: () => new Promise(resolve => listener({ cmd: 'humanProbe' }, {}, resolve)) };
}

function popup(sendMessage) {
  const timers = new Map();
  let sequence = 0;
  const elements = {
    humanProbe: { disabled: false },
    humanProbeStatus: { hidden: true, textContent: '' },
  };
  const chrome = { runtime: { sendMessage } };
  const context = vm.createContext({ $: id => elements[id], chrome, render: () => {},
    setTimeout: (fn, ms) => { const id = ++sequence; timers.set(id, { fn, ms }); return id; },
    clearTimeout: id => timers.delete(id) });
  const start = popupSource.indexOf("$('humanProbe').onclick");
  const end = popupSource.indexOf('// 🖱', start);
  assert(start >= 0 && end > start);
  vm.runInContext(popupSource.slice(start, end), context);
  return { elements, chrome, timers, click: () => elements.humanProbe.onclick() };
}

test('an HTTP failure is returned to the diagnostic caller without throwing', async () => {
  const w = worker({ fetch: async () => ({ ok: false, status: 503 }) });
  const result = await w.context.reportBlocked({ err: 'HUMAN_PROBE' });
  assert.equal(result?.ok, false);
  assert.equal(result.code, 'HTTP_ERROR');
  assert.equal(result.status, 503);
  assert.equal(w.calls.length, 1);
});

test('only an HTTP success with JSON success true confirms receipt', async () => {
  for (const [body, expected] of [[{ success: true }, true], [{ success: false }, false],
    [{}, false], [null, false], [{ success: 'true' }, false]]) {
    const w = worker({ fetch: async () => ({ ok: true, status: 200, json: async () => body }) });
    const result = await w.context.reportBlocked({ err: 'HUMAN_PROBE' });
    assert.equal(result?.ok, expected, JSON.stringify(body));
    if (!expected) assert.equal(result.code, 'NEGATIVE_ACK');
    assert.equal(w.timers.size, 0);
  }
  const malformed = worker({ fetch: async () => ({ ok: true, status: 200, json: async () => { throw Error('private response'); } }) });
  const result = await malformed.context.reportBlocked({});
  assert.equal(result.ok, false);
  assert.equal(result.code, 'INVALID_ACK');
  assert(!JSON.stringify(result).includes('private response'));
});

test('missing credentials and network failure are explicit safe failures with no retry', async () => {
  const missing = worker({ token: '' });
  assert.equal((await missing.context.reportBlocked({}))?.code, 'NO_TOKEN');
  assert.equal(missing.calls.length, 0);
  const disconnected = worker({ fetch: async () => { throw Error('SENTINEL_PRIVATE_TOKEN private network detail'); } });
  const result = await disconnected.context.reportBlocked({});
  assert.equal(result.ok, false);
  assert.equal(result.code, 'NETWORK_ERROR');
  assert.equal(disconnected.calls.length, 1);
  assert(!JSON.stringify(result).includes('SENTINEL_PRIVATE_TOKEN'));
});

test('a stalled request or ACK body times out, aborts, and never retries', async () => {
  for (const stalledBody of [false, true]) {
    const never = new Promise(() => {});
    const w = worker({ fetch: async () => stalledBody ? { ok: true, status: 200, json: () => never } : never });
    const pending = w.context.reportBlocked({});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(w.timers.size, 1, 'delivery must have a deadline');
    const timer = [...w.timers.values()][0];
    assert(timer.ms > 0 && timer.ms <= 15000);
    timer.fn();
    const result = await pending;
    assert.equal(result.ok, false);
    assert.equal(result.code, 'TIMEOUT');
    assert.equal(w.calls[0].init.signal.aborted, true);
    assert.equal(w.calls.length, 1);
    assert.equal(w.timers.size, 0);
  }
});

test('manual diagnostics wait for the server before replying or logging success', async () => {
  let release;
  const response = new Promise(resolve => { release = resolve; });
  const w = worker({ fetch: () => response });
  let replied = false;
  const pending = w.message().then(result => { replied = true; return result; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(replied, false, 'enqueueing is not a server receipt');
  assert.equal(w.logs.length, 0);
  release({ ok: false, status: 503 });
  const result = await pending;
  assert.equal(result.ok, false);
  assert.equal(result.code, 'HTTP_ERROR');
  assert(w.logs.some(line => /503/.test(line)));
  assert(w.logs.every(line => !/수신을 확인했습니다|서버에 보냈습니다/.test(line)));
});

test('missing tab, token, and failed or empty injection never claim delivery', async () => {
  for (const [options, code] of [
    [{ query: async () => [] }, 'NO_TAB'],
    [{ token: '' }, 'NO_TOKEN'],
    [{ inject: async () => { throw Error('private browser error'); } }, 'INJECTION_FAILED'],
    [{ inject: async () => [] }, 'INJECTION_FAILED'],
    [{ inject: async () => [{ result: null }] }, 'INJECTION_FAILED'],
  ]) {
    const w = worker(options);
    const result = await w.message();
    assert.equal(result?.ok, false);
    assert.equal(result.code, code);
    assert.equal(w.calls.length, 0);
    assert(!JSON.stringify(result).includes('private browser error'));
  }
});

test('popup disables duplicate sends until a real server ACK and displays the result', async () => {
  let release;
  const w = worker({ fetch: () => new Promise(resolve => { release = resolve; }) });
  let messages = 0;
  const p = popup((_message, reply) => { messages++; w.message().then(reply); });
  p.click(); p.click();
  assert.equal(p.elements.humanProbe.disabled, true);
  assert.equal(p.elements.humanProbeStatus.hidden, false);
  assert.equal(messages, 1);
  await new Promise(resolve => setImmediate(resolve));
  assert(!/✅/.test(p.elements.humanProbeStatus.textContent));
  release({ ok: true, status: 200, json: async () => ({ success: true }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.elements.humanProbe.disabled, false);
  assert.match(p.elements.humanProbeStatus.textContent, /✅.*수신/);
  assert.equal(w.calls.length, 1);
  assert(w.calls.every(call => call.url === 'https://server.invalid/api/collector/blocked'));
});

test('popup safely recovers from message-channel failures and shows server failures', async () => {
  const throwing = popup(() => { throw Error('SENTINEL_PRIVATE_TOKEN extension invalidated'); });
  assert.doesNotThrow(() => throwing.click());
  assert.equal(throwing.elements.humanProbe.disabled, false);
  assert.match(throwing.elements.humanProbeStatus.textContent, /⚠️/);
  assert(!throwing.elements.humanProbeStatus.textContent.includes('SENTINEL_PRIVATE_TOKEN'));

  let reply, errorRead = false;
  const closed = popup((_message, callback) => { reply = callback; });
  Object.defineProperty(closed.chrome.runtime, 'lastError', { get: () => {
    errorRead = true; return { message: 'SENTINEL_PRIVATE_TOKEN port closed' };
  } });
  closed.click(); reply(undefined);
  assert.equal(errorRead, true, 'Chrome lastError must be consumed');
  assert.equal(closed.elements.humanProbe.disabled, false);
  assert.match(closed.elements.humanProbeStatus.textContent, /⚠️/);
  assert(!closed.elements.humanProbeStatus.textContent.includes('SENTINEL_PRIVATE_TOKEN'));

  const empty = popup((_message, callback) => callback(undefined));
  empty.click();
  assert.equal(empty.elements.humanProbe.disabled, false);
  assert.match(empty.elements.humanProbeStatus.textContent, /⚠️.*확인하지/);

  const w = worker({ fetch: async () => ({ ok: false, status: 401 }) });
  const rejected = popup((_message, callback) => w.message().then(callback));
  rejected.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(rejected.elements.humanProbe.disabled, false);
  assert.match(rejected.elements.humanProbeStatus.textContent, /⚠️.*HTTP 401/);
});

test('popup times out a lost callback and ignores its late result after another click', () => {
  const replies = [];
  const p = popup((_message, reply) => replies.push(reply));
  p.click();
  const deadline = [...p.timers.values()].find(timer => timer.ms > 0 && timer.ms <= 15000);
  assert(deadline, 'popup must not remain disabled forever');
  deadline.fn();
  assert.equal(p.elements.humanProbe.disabled, false);
  assert.match(p.elements.humanProbeStatus.textContent, /⚠️.*시간.*미확인|⚠️.*시간.*확인하지/);
  assert.equal(replies.length, 1, 'timeout must not resend automatically');
  p.click();
  replies[0]({ ok: true, message: 'old success' });
  assert.equal(p.elements.humanProbe.disabled, true);
  assert(!p.elements.humanProbeStatus.textContent.includes('old success'));
  replies[1]({ ok: false, message: 'current failure' });
  assert.equal(p.elements.humanProbe.disabled, false);
  assert.match(p.elements.humanProbeStatus.textContent, /current failure/);
});

test('automatic diagnostics remain nonthrowing and respect the remote switch', async () => {
  const disabled = worker({ remote: { swTapProbe: false } });
  await assert.doesNotReject(() => disabled.context.tapReport(2, 'keyword', 1, 'UNVERIFIED_PAGE'));
  assert.equal(disabled.calls.length, 0);
  assert.equal((await disabled.message()).ok, true, 'manual diagnostics remain available');
  assert.equal(disabled.calls.length, 1);

  const failed = worker({ fetch: async () => { throw Error('offline'); } });
  await assert.doesNotReject(() => failed.context.tapReport(2, 'keyword', 1, 'UNVERIFIED_PAGE'));
  assert.equal(failed.calls.length, 1);
  assert.equal(failed.logs.length, 0, 'automatic diagnostics do not change the manual log flow');
});
