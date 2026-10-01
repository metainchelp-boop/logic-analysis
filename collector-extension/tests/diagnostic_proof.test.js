'use strict';
// Real injected/worker functions; no network or browser requests.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
function grab(name) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert(start >= 0, name);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw Error('Unclosed ' + name);
}
function page(items = [], href = 'https://search.shopping.naver.com/search/all?query=private-query', tap = true) {
  const nd = { query: { query: 'private-query' }, products: [{ productTitle: 'private-product', nvMid: 'private-id' }] };
  const router = { route: '/search/all', query: { query: 'private-query' }, components: { '/search/all': { props: nd } } };
  const window = { __NEXT_DATA__: nd, next: { router }, __mcReadBaseline: { keyword: 'private-query', router: nd, nextdata: nd } };
  if (tap) window.__mcTap = { items: [], misses: items };
  const context = vm.createContext({ URL, window, location: { href, search: new URL(href).search },
    document: { title: 'private-title', body: { innerText: 'private-body' } } });
  vm.runInContext(grab('pageExtract'), context);
  return context.pageExtract({ keyword: 'private-query', page: 2, since: 1000 });
}
const entry = overrides => Object.assign({ page: 2, keyword: 'private-query', requestStartedAt: 1100, status: 200,
  sourceKnown: true, scopeVerified: true, responseMatched: true, json: {} }, overrides);

test('failed reader exposes existing gates and ignores unrelated page-zero HTTP 418', () => {
  const result = page([entry({ page: 0, keyword: '', status: 418 })]);
  assert.equal(result.err, 'UNVERIFIED_PAGE');
  assert.equal(result.diag?.urlPage, 1);
  assert.equal(result.diag?.location, false);
  assert.equal(result.diag?.tap.n, 1);
  assert.equal(result.diag?.tap.page, 0);
  assert.equal(result.diag?.tap.fresh, 0);
  assert.equal(result.diag?.tap.status, 0);
});

test('capture gate stages distinguish missing tap, stale response, identity rejection and restricted matching response', () => {
  assert.equal(page([], undefined, false).diag?.tap.on, false);
  for (const [override, key] of [[{ requestStartedAt: 999 }, 'fresh'], [{ responseMatched: false }, 'response'],
    [{ scopeVerified: false }, 'scope'], [{ sourceKnown: false }, 'source'], [{ keyword: 'other' }, 'keyword']]) {
    const result = page([entry(override)]);
    assert.equal(result.err, 'UNVERIFIED_PAGE');
    assert.equal(result.diag?.tap[key], 0, key);
    assert.equal(result.diag?.tap.status, 0, key);
  }
  const restricted = page([entry({ status: 418 })]);
  assert.equal(restricted.err, 'HTTP_RESTRICTED');
  assert.equal(restricted.diag?.tap.fresh, 1);
  assert.equal(restricted.diag?.tap.status, 418);
  assert.equal(restricted.diag?.checked, false, 'preserve early HTTP classification before route gates');
  const arrived = page([entry()]);
  assert.equal(arrived.diag?.tap.fresh, 1);
  assert.equal(arrived.diag?.tap.status, 200);
  assert.equal(arrived.diag?.location, false, 'data arrival does not prove current URL page');
});

test('TAP_PROBE remains valid bounded JSON with only allowed diagnostics, never raw content', async () => {
  const reports = [];
  const secret = 'PRIVATE_QUERY_HREF_CLASS_PRODUCT_ERROR_' + 'x'.repeat(2000);
  const context = vm.createContext({ RT: {}, _lastClickBranch: 'loose', _lastClickHow: 'trusted', _clickCovered: 1,
    _clickHit: secret, _trustedNote: secret, _pagerAfter: secret,
    navProbe: () => {}, chrome: { scripting: { executeScript: async () => [{ result: {
      href: secret, q: secret, env: secret, urlPage: 1,
      tap: { n: 6, m: 20, items: [secret], misses: [secret] } } }] } },
    reportBlocked: async report => { reports.push(report); return { ok: true }; } });
  vm.runInContext(grab('tapReport'), context);
  const proof = page([entry({ page: 0, status: 418 })]).diag;
  assert.equal((await context.tapReport(1, secret, 2, 'UNVERIFIED_PAGE', undefined, proof)).ok, true);
  const body = reports[0].body;
  assert(body.length <= 500, body.length);
  const compact = JSON.parse(body);
  assert.equal(compact.want, 2);
  assert.equal(compact.now, 1);
  assert.equal(compact.click.branch, 'loose');
  assert.equal(compact.click.how, 'trusted');
  assert.equal(compact.click.covered, true);
  assert.equal(compact.tap.status, 0);
  assert(!body.includes('PRIVATE_'));
  assert(!body.includes('private-'));
  context._lastClickBranch = secret; context._lastClickHow = secret;
  await context.tapReport(1, secret, 1e300, secret, undefined,
    { urlPage: 1e300, tap: { n: 1e300, page: secret, status: 1e300 } });
  assert(reports[1].body.length <= 500);
  assert(!reports[1].body.includes('PRIVATE_'));
  JSON.parse(reports[1].body);
  context._lastClickBranch = 'pending'; context._lastClickHow = 'trusted'; context._clickCovered = 0;
  await context.tapReport(1, secret, 999, 'UNVERIFIED_PAGE', undefined, { urlPage: 999,
    tap: Object.fromEntries(['n','page','keyword','source','scope','response','fresh','status'].map(key => [key, 999])) });
  assert(reports[2].body.length <= 500, 'all maximum bounded values still fit');
  JSON.parse(reports[2].body);
});

test('navProbe reports numeric current URL page, not stale router page or truncated href', () => {
  const context = vm.createContext({ URL, window: { next: { router: { query: { pagingIndex: '99' } } } },
    location: { href: 'https://search.shopping.naver.com/search/all?query=' + 'x'.repeat(300) + '&pagingIndex=2' }, document: {} });
  vm.runInContext(grab('navProbe'), context);
  assert.equal(context.navProbe().urlPage, 2);
  context.location.href = 'https://search.shopping.naver.com/search/all?query=x';
  assert.equal(context.navProbe().urlPage, 1);
  context.location.href += '&pagingIndex=2&pagingIndex=3';
  assert.equal(context.navProbe().urlPage, 0);
});

test('fetchPage clears all previous click evidence before its first page operation', async () => {
  const context = vm.createContext({ _lastClickBranch: 'loose', _lastClickHow: 'trusted', _clickHit: 'old',
    _clickCovered: 1, _clickProof: { state: 'received', ev: 255 }, _pagerAfter: 'old', _trustedNote: 'old',
    ensureWorkTab: async () => { throw Error('stop before work'); } });
  vm.runInContext(grab('fetchPage'), context);
  await assert.rejects(context.fetchPage('new', 1), /stop before work/);
  for (const key of ['_lastClickBranch', '_lastClickHow', '_clickHit', '_pagerAfter', '_trustedNote']) assert.equal(context[key], '', key);
  assert.equal(context._clickCovered, 0);
  assert.equal(context._clickProof, null);
});

test('guard receipt is bounded, private and distinct from verified navigation', async () => {
  const reports = [];
  const context = vm.createContext({ RT: {}, _lastClickBranch: 'pending', _lastClickHow: 'trusted', _clickCovered: 0,
    _clickProof: { state: 'unavailable', ev: 511, gone: false, js: 9, geo: 'LT2:-9999,-9999,9999,9999', raw: 'PRIVATE_TARGET_TEXT' },
    navProbe: () => {}, chrome: { scripting: { executeScript: async () => [{ result: { env: 'f1v1a10w0r1', urlPage: 999 } }] } },
    reportBlocked: async report => { reports.push(report); return { ok: true }; } });
  vm.runInContext(grab('tapReport'), context);
  const proof = { urlPage: 999, tap: Object.fromEntries(['n','page','keyword','source','scope','response','fresh','status'].map(key => [key, 999])) };
  await context.tapReport(1, 'fixture', 999, 'UNVERIFIED_PAGE', undefined, proof);
  const first = JSON.parse(reports[0].body);
  assert.equal(first.click.guard, 'unavailable');
  assert.equal(first.click.ev, 511);
  assert.equal(first.click.gone, false);
  assert.equal(first.click.js, 9);
  assert.equal(first.click.geo, 'LT2:-9999,-9999,9999,9999');
  assert.equal(first.gates.location, false);
  assert(reports[0].body.length <= 500, reports[0].body.length);
  assert(!reports[0].body.includes('PRIVATE'));
  context._clickProof = { state: 'PRIVATE_TARGET', ev: 1e300, gone: 'PRIVATE', js: 1e300, geo: 'PRIVATE_TARGET_TEXT' };
  await context.tapReport(1, 'fixture', 999, 'UNVERIFIED_PAGE', undefined, proof);
  const second = JSON.parse(reports[1].body);
  assert.equal(second.click.guard, 'none');
  assert.equal(second.click.geo, 'none');
  assert.equal(second.click.ev, 511); assert.equal(second.click.js, 9); assert.equal(second.click.gone, null);
  assert(reports[1].body.length <= 500); assert(!reports[1].body.includes('PRIVATE'));
  await context.tapReport(1, '(manual)', 0, 'HUMAN');
  assert.equal(JSON.parse(reports[2].body).click, undefined, 'manual report must not reuse past click evidence');
  for (const geo of ['I3:1,2,3,4', 'B2:10000,2,3,4', 'I0:NaN,2,3,4', 'I0:1,2,-3,4', 'I0:1,2,3,4\nPRIVATE', 'I0:1,2,3,4\n']) {
    context._clickProof = { state: 'outside', geo };
    await context.tapReport(1, 'fixture', 2, 'NO_PAGER', undefined, proof);
    assert.equal(JSON.parse(reports.at(-1).body).click.geo, 'none', geo);
  }
  context._clickProof = { state: 'unavailable', ev: null, gone: false, js: null, geo: 'LT2:-9999,-9999,9999,9999' };
  await context.tapReport(1, 'fixture', 999, 'UNVERIFIED_PAGE', undefined, proof);
  assert(reports.at(-1).body.length <= 500, 'nullable receipt fields and longest geometry still fit');
  assert.equal(JSON.parse(reports.at(-1).body).click.geo, context._clickProof.geo);
});

test('fetchPage passes last read proof to the existing single failure TAP_PROBE without another read or click', async () => {
  const calls = [], reports = [];
  const failure = page([entry({ page: 0, status: 418 })]);
  let reads = 0, clicks = 0;
  const context = vm.createContext({ _lastClickBranch: '', _lastClickHow: '', _clickHit: '', _clickCovered: 0,
    _pagerAfter: '', _trustedNote: '', _clickedAt: 0, _navMode: { click: 0 },
    ensureWorkTab: async () => 1, waitNavigated: async () => {}, isBlockedUrl: () => false,
    sleep: async () => {}, CFG: { readTries: 2, readTriesPaged: 2, readGapMs: 0 },
    pageExtract: () => {}, clickToPage: async () => { clicks++; return true; },
    reportBlocked: report => reports.push(report), tapReport: async (...args) => calls.push(args),
    chrome: { tabs: { get: async () => ({ url: 'https://search.shopping.naver.com/search/all?query=private-query' }) },
      scripting: { executeScript: async ({ args }) => { if (args[0].snapshot) return [{ result: {} }]; reads++; return [{ result: failure }]; } },
      storage: { local: { set: async () => {} } } } });
  vm.runInContext(grab('fetchPage'), context);
  await assert.rejects(context.fetchPage('private-query', 2, []), /UNVERIFIED_PAGE/);
  assert.equal(clicks, 1); assert.equal(reads, 2); assert.equal(reports.length, 1); assert.equal(calls.length, 1);
  assert.equal(calls[0][5], failure.diag);
});

test('manual reports preserve typed recent response identity and environment without raw contents or extra requests', async () => {
  const reports = [];
  let requests = 0, injections = 0;
  const secret = 'PRIVATE_QUERY_PRODUCT_BODY_PATH';
  const context = vm.createContext({ URL, Date: { now: () => 200000 }, RT: {},
    location: new URL('https://search.shopping.naver.com/search/all?query=private-query&pagingIndex=2'),
    navigator: { userActivation: { hasBeenActive: true, isActive: false }, webdriver: false },
    document: { hasFocus: () => true, visibilityState: 'visible', referrer: 'present', querySelectorAll: () => [] },
    window: { __mcTap: { items: [
      entry({ at: 100000, page: 1, ids: [secret], path: secret }),
      entry({ at: 198000, page: 2, ids: [secret], path: secret }),
      entry({ at: 197000, page: 2, keyword: 'different', responseMatched: false, ids: [secret] }),
    ], misses: [entry({ at: 199000, page: 0, keyword: '', status: 418,
      sourceKnown: false, scopeVerified: false, responseMatched: null, head: secret, path: secret })] } },
    fetch: () => { requests++; throw Error('No network permitted'); },
    reportBlocked: async report => { reports.push(report); return { ok: true, code: 'ACKNOWLEDGED' }; },
  });
  context.chrome = { scripting: { executeScript: async () => { injections++; return [{ result: context.navProbe() }]; } } };
  vm.runInContext(grab('navProbe') + '\n' + grab('tapReport'), context);
  const result = await context.tapReport(1, '(사람 시험)', 0, 'HUMAN', 'HUMAN_PROBE');
  assert.equal(result.code, 'ACKNOWLEDGED');
  assert.equal(reports.length, 1); assert.equal(requests, 0); assert.equal(injections, 1);
  const body = JSON.parse(reports[0].body);
  assert.equal(body.env, 'f1v1a10w0r1');
  assert.equal(body.now, 2); assert.equal(body.tap.n, 4);
  assert.equal(body.tap.recent.length, 3);
  assert.deepEqual(body.tap.recent.map(item => [item.page, item.status, item.age, item.known, item.scope, item.response, item.query]), [
    [0, 418, 1, false, false, null, false],
    [2, 200, 2, true, true, true, true],
    [2, 200, 3, true, true, false, false],
  ]);
  assert(reports[0].body.length <= 500, reports[0].body.length);
  assert(!reports[0].body.includes(secret)); assert(!reports[0].body.includes('private-query'));
  assert.equal(body.gates, undefined); assert.equal(body.click, undefined);
});

test('baseline diagnostics distinguish no comparison, same object and changed data without changing reader acceptance', () => {
  const data = { query: { query: 'fixture' }, products: [{ nvMid: '1', productTitle: 'Fixture', mallName: 'Fixture' }] };
  const context = vm.createContext({ URL, window: { __NEXT_DATA__: data },
    location: new URL('https://search.shopping.naver.com/search/all?query=fixture'), document: { body: { innerText: '' } } });
  vm.runInContext(grab('pageExtract'), context);
  const want = { keyword: 'fixture', page: 1, since: 1000 };
  const first = context.pageExtract(want);
  assert.equal(first.err, undefined); assert.equal(first.verified, true);
  assert.equal(first.diag.baseline, false); assert.equal(first.diag.nextChanged, false);
  context.pageExtract({ ...want, snapshot: true });
  const same = context.pageExtract(want);
  assert.equal(same.err, 'UNVERIFIED_PAGE');
  assert.equal(same.diag.baseline, true); assert.equal(same.diag.nextChanged, false);
  context.window.__NEXT_DATA__ = JSON.parse(JSON.stringify(data));
  const changed = context.pageExtract(want);
  assert.equal(changed.err, undefined); assert.equal(changed.verified, true);
  assert.equal(changed.diag.baseline, true); assert.equal(changed.diag.nextChanged, true);
});

test('manual and automatic reports fit the cap at maximum scalar lengths and reject raw environment or entry data', async () => {
  const reports = [];
  const secret = 'PRIVATE_BODY_QUERY_TOKEN';
  const probe = { env: 'f1v1a10w0r1', urlPage: 999, tapCount: 999, tapPresent: false,
    recent: Array.from({ length: 5 }, () => ({ page: 999, status: 999, age: 999,
      known: false, scope: false, response: false, query: false, raw: secret })) };
  const context = vm.createContext({ RT: {}, _lastClickBranch: 'pending', _lastClickHow: 'trusted', _clickCovered: 0,
    navProbe: () => {}, chrome: { scripting: { executeScript: async () => [{ result: probe }] } },
    reportBlocked: async report => { reports.push(report); return { ok: true }; } });
  vm.runInContext(grab('tapReport'), context);
  await context.tapReport(1, '(사람 시험)', 0, 'HUMAN');
  const manual = JSON.parse(reports[0].body);
  assert.equal(manual.tap.recent.length, 3);
  assert.equal(manual.env, 'f1v1a10w0r1');
  assert(reports[0].body.length <= 500, reports[0].body.length);
  const proof = { urlPage: 999, baseline: true,
    tap: Object.fromEntries(['n','page','keyword','source','scope','response','fresh','status'].map(key => [key, 999])) };
  await context.tapReport(1, 'fixture', 999, 'UNVERIFIED_PAGE', undefined, proof);
  const automatic = JSON.parse(reports[1].body);
  assert.equal(automatic.gates.baseline, true);
  assert.equal(automatic.env, 'f1v1a10w0r1');
  assert(reports[1].body.length <= 500, reports[1].body.length);
  probe.env = secret;
  probe.recent = [{ page: secret, status: 1e300, age: Infinity,
    known: secret, scope: {}, response: [], query: secret, raw: secret }];
  await context.tapReport(1, '(사람 시험)', 0, 'HUMAN');
  const sanitized = JSON.parse(reports[2].body);
  assert.equal(sanitized.env, 'none');
  assert.equal(sanitized.tap.recent[0].known, null);
  assert.equal(sanitized.tap.recent[0].query, null);
  for (const report of reports) { assert(report.body.length <= 500); assert(!report.body.includes(secret)); }
});

test('manual recent keeps two known search responses after three newer auxiliary responses', () => {
  const context = vm.createContext({ URL, Date: { now: () => 200000 },
    location: new URL('https://search.shopping.naver.com/search/all?query=private-query&pagingIndex=2'),
    document: {}, window: { __mcTap: {
      items: [entry({ at: 191000, page: 2, status: 200 })],
      misses: [entry({ at: 192000, page: 2, status: 418 }),
        ...[193000, 194000, 195000].map(at => entry({ at, page: 0, status: 418, keyword: '', sourceKnown: false }))],
    } } });
  vm.runInContext(grab('navProbe'), context);
  const recent = JSON.parse(JSON.stringify(context.navProbe().recent));
  assert.equal(recent.length, 3);
  assert.deepEqual(recent.filter(item => item.known).map(item => [item.page, item.status, item.age, item.query]),
    [[2, 418, 8, true], [2, 200, 9, true]]);
  assert.deepEqual(recent.filter(item => !item.known).map(item => [item.page, item.status, item.age, item.query]),
    [[0, 418, 5, false]]);
});
