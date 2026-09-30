// Full service-worker runtime; only Chrome, HTTP, time and page-world boundaries are fixtures.
// No production network, profile, token or DB. Collection/upload/rest/alarm code is unmodified.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const dir = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(dir, 'background.js'), 'utf8');
const START = new Date('2026-09-30T10:10:00+09:00').getTime();
const lease = keyword => ({ state: 'LEASED', job: { keyword, jobId: 'j-' + keyword,
  leaseId: 'l-' + keyword, workerId: 'fixture', sessionId: 'fixture-session', targetIds: [keyword + '-1'] } });

function fixture({ store = {}, claims = [], block = '', clock = { now: START }, register = { enabled: true, state: 'READY' }, onUpload } = {}) {
  const data = Object.assign({ token: 'fixture-only', instanceId: 'fixture', coordinatedEnabled: true,
    remoteSettings: { values: { swSearchEntry: false } } }, store);
  const calls = [], uploads = [], listeners = {};
  let claimIndex = 0;
  const tabs = new Map([[1, { id: 1, windowId: 1, active: false, status: 'complete',
    url: 'https://search.shopping.naver.com/search/all?query=fixture' }]]);
  const area = {
    get: async keys => structuredClone(Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, data[k]]))),
    set: async patch => Object.assign(data, structuredClone(patch)),
    remove: async keys => { for (const k of Array.isArray(keys) ? keys : [keys]) delete data[k]; },
  };
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock.now])); }
    static now() { return clock.now; }
  }
  const context = vm.createContext({ console, URL, Set, Map, Date: ClockDate,
    crypto: require('node:crypto').webcrypto,
    setTimeout: fn => setImmediate(fn), clearTimeout: clearImmediate,
    setInterval: fn => setImmediate(fn), clearInterval: clearImmediate,
    fetch: async (url, init = {}) => {
      const endpoint = new URL(url).pathname;
      const body = init.body ? JSON.parse(init.body) : {};
      calls.push({ endpoint, body, at: clock.now });
      let result = {};
      if (endpoint.endsWith('/v2/register')) result = register;
      else if (endpoint.endsWith('/v2/claim')) result = claims[claimIndex++] || { state: 'IDLE' };
      else if (endpoint.endsWith('/serp')) {
        uploads.push(body); result = { stored: true, observationId: body.meta.observation.observationId };
        if (onUpload) onUpload(clock);
      }
      if (result instanceof Error) throw result;
      return { ok: true, status: 200, json: async () => result };
    },
    chrome: {
      storage: { local: area, session: area },
      runtime: { id: 'fixture', getManifest: () => JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'))),
        onInstalled: { addListener() {} }, onStartup: { addListener() {} },
        onMessage: { addListener: fn => { listeners.message = fn; } } },
      alarms: { get: async name => ({ name, periodInMinutes: name === 'daily' ? 1 : 5 }),
        create() {}, getAll: async () => [], onAlarm: { addListener: fn => { listeners.alarm = fn; } } },
      tabs: {
        get: async id => { if (!tabs.has(id)) throw Error('Tab gone'); return tabs.get(id); },
        query: async () => [...tabs.values()],
        update: async (id, patch) => { Object.assign(tabs.get(id), patch); return tabs.get(id); },
        remove: async id => tabs.delete(id),
      },
      scripting: { executeScript: async ({ func, args = [] }) => {
        if (func.name !== 'pageExtract' || args[0].snapshot) return [{ result: {} }];
        const { keyword, page } = args[0];
        if (keyword === block) return [{ result: { err: 'BLOCK_TEXT', title: 'fixture captcha' } }];
        return [{ result: { total: 100, src: 'nextdata', verified: true, keyword, pageIndex: page,
          href: 'https://search.shopping.naver.com/search/all?query=' + keyword,
          list: [{ nvMid: keyword + '-1', productTitle: 'Fixture product' }] } }];
      } },
    },
  });
  context.importScripts = (...files) => files.forEach(file => vm.runInContext(fs.readFileSync(path.join(dir, file), 'utf8'), context));
  vm.runInContext(source, context, { filename: 'background.js' });
  return { data, calls, uploads, clock, alarm: (name = 'daily') => listeners.alarm({ name }),
    command: cmd => listeners.message({ cmd }, {}, () => {}) };
}

test('success then restriction preserves cooldown and prevents automatic retry after worker restart', async () => {
  const f = fixture({ claims: [lease('ok'), lease('blocked')], block: 'blocked' });
  await f.alarm();
  assert.equal(f.uploads.length, 1, JSON.stringify(f.data));
  assert.equal(f.data.state.blocked, true);
  assert.equal(f.data.blockedUntil, START + 6 * 3600000);
  assert.equal(f.data.slowUntil, START + 24 * 3600000);
  const restarted = fixture({ store: f.data, clock: { now: START + 2 * 3600000 } });
  await restarted.alarm();
  await restarted.alarm('ondemand');
  for (let i = 0; i < 5; i++) await new Promise(setImmediate);
  assert.equal(restarted.calls.length, 0, 'no central or on-demand collection while cooling down');
  assert.equal(restarted.data.blockedUntil, f.data.blockedUntil);
});

test('exhausted local round budget waits until the next hour instead of resetting every minute', async () => {
  const f = fixture({ claims: [lease('long')], onUpload: clock => { clock.now += 46 * 60000; } });
  await f.alarm();
  assert.equal(f.uploads.length, 1);
  const nextHour = new Date(START); nextHour.setHours(nextHour.getHours() + 1, 0, 0, 0);
  assert.equal(Date.parse(f.data.state.coordNextAt), nextHour.getTime());
  const resumed = fixture({ store: f.data, clock: { now: f.clock.now + 60000 }, claims: [lease('after')] });
  await resumed.alarm();
  assert.equal(resumed.calls.length, 0);
  resumed.clock.now = nextHour.getTime();
  await resumed.alarm();
  assert.equal(resumed.uploads.length, 1);
});

test('temporary budget wait survives restart, makes no early claims and resumes within the same hour', async () => {
  const deadline = START + 3 * 60000;
  const f = fixture({ claims: [lease('first'), { state: 'WAIT_BUDGET', reason: 'MIN_GAP', nextAllowedAt: deadline / 1000 }] });
  await f.alarm();
  assert.equal(f.uploads.length, 1);
  assert.equal(f.data.state.finishedHour, undefined, 'a temporary wait is not hour completion');
  assert.equal(Date.parse(f.data.state.coordNextAt), deadline);
  const restarted = fixture({ store: f.data, claims: [lease('second')], clock: { now: deadline - 1 } });
  await restarted.alarm();
  assert.equal(restarted.calls.length, 0, 'no registration/claim before the persisted deadline');
  restarted.clock.now = deadline;
  await restarted.alarm();
  assert.equal(restarted.uploads.length, 1, JSON.stringify(restarted.data.state));
  assert.equal(restarted.uploads[0].keyword, 'second');
  assert.equal(restarted.data.state.coordNextAt, '', 'expired wait must not remain on the popup');
});

test('malformed or absent nextAllowedAt cannot crash the waiting state or prevent next-minute retry', async () => {
  for (const invalid of ['bad-date', 1e300, undefined]) {
    const f = fixture({ claims: [{ state: 'WAIT_BUDGET', nextAllowedAt: invalid }, lease('retry')] });
    await f.alarm();
    assert.equal(f.data.state.coordState, 'WAIT_BUDGET');
    assert.equal(f.data.state.coordNextAt, '');
    assert.equal(f.data.state.error, undefined);
    f.clock.now += 60000;
    await f.alarm();
    assert.equal(f.uploads.length, 1);
  }
});

test('a legacy/old-version hour marker does not suppress central work, but still guards legacy fallback', async () => {
  const d = new Date(START);
  const finishedHour = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}:${String(d.getHours()).padStart(2, '0')}`;
  const f = fixture({ store: { state: { finishedHour } }, claims: [lease('new')] });
  await f.alarm();
  assert.equal(f.uploads.length, 1);
  assert.equal(f.data.state.finishedHour, finishedHour, 'central path must preserve the legacy marker');
  const legacy = fixture({ store: { coordinatedEnabled: false, state: { finishedHour } } });
  await legacy.alarm();
  assert.equal(legacy.calls.length, 0);
  const inactive = fixture({ store: { state: { finishedHour } }, register: { enabled: false } });
  await inactive.alarm();
  assert.deepEqual(inactive.calls.map(c => c.endpoint), ['/api/collector/v2/register']);
});

test('IDLE and transient claim errors after success leave the same hour eligible for rechecking', async () => {
  for (const ending of [{ state: 'IDLE' }, new Error('fixture network failure')]) {
    const f = fixture({ claims: [lease('first'), ending, lease('later')] });
    await f.alarm();
    assert.equal(f.uploads.length, 1);
    f.clock.now += 60000;
    await f.alarm();
    assert.equal(f.uploads.length, 2);
    assert.equal(f.uploads[1].keyword, 'later');
  }
});

test('operator pauses and server deadlines are not bypassed by manual start', async () => {
  for (const store of [{ localPaused: true }, { remoteSettings: { values: { machinePaused: true } } },
    { state: { coordNextAt: new Date(START + 60000).toISOString() } }]) {
    const f = fixture({ store });
    await f.alarm();
    f.command('run');
    for (let i = 0; i < 5; i++) await new Promise(setImmediate);
    assert.equal(f.calls.length, 0);
  }
});

test('healthy run can clear an expired block without dropping the slower recovery window', async () => {
  const f = fixture({ store: { blockedUntil: START - 1, slowUntil: START + 86400000,
    state: { blocked: true, blockedUntil: START - 1 } }, claims: [lease('healthy')] });
  await f.alarm();
  assert.equal(f.uploads.length, 1);
  assert.equal(f.data.state.blocked, false);
  assert.equal(f.data.blockedUntil, undefined);
  assert.equal(f.data.slowUntil, START + 86400000);
});

test('a job crossing the hour boundary does not postpone resumption for an extra hour', async () => {
  const clock = { now: START + 49 * 60000 }; // 10:59 KST
  const f = fixture({ clock, claims: [lease('cross-hour')], onUpload: c => { c.now += 2 * 60000; } });
  await f.alarm();
  assert.equal(f.uploads.length, 1);
  const boundary = new Date(START); boundary.setHours(boundary.getHours() + 1, 0, 0, 0);
  assert.equal(Date.parse(f.data.state.coordNextAt), boundary.getTime());
  const restarted = fixture({ store: f.data, clock: { now: clock.now + 60000 }, claims: [lease('next-hour')] });
  await restarted.alarm();
  assert.equal(restarted.uploads.length, 1);
});
