/* Offline diagnostic only. Reads real functions from the frozen source; all browser/network APIs are fakes. */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'background.js'), 'utf8');
const tapSrc = fs.readFileSync(path.join(root, 'net_tap.js'), 'utf8');
const RR = require(path.join(root, 'rank_rules.js'));
// Same extraction seam as the existing human_nav.test.js; compilation fails if extraction is invalid.
function grab(name, async = false) {
  const start = src.indexOf(`${async ? 'async ' : ''}function ${name}(`);
  assert(start >= 0, `Missing ${name}`);
  let depth = 0, end = src.indexOf('{', start);
  for (; end < src.length; end++) {
    if (src[end] === '{') depth++;
    if (src[end] === '}' && --depth === 0) { end++; break; }
  }
  return src.slice(start, end);
}
const products = ids => ids.map(id => ({ nvMid: String(id), productTitle: `Product ${id}`, mallName: 'Store' }));
const payload = ids => ({ shoppingResult: { total: 1000, products: products(ids) } });
const p1 = [1, 2, 3];
const p2 = [41, 42, 43];
const loc = { href: 'https://search.shopping.naver.com/search/all?query=current&pagingIndex=2', search: '?query=current&pagingIndex=2' };
function scene(routerIds = p1, items = []) {
  return {
    __NEXT_DATA__: payload(p1),
    next: { router: { route: '/search/all', query: { query: 'current', pagingIndex: '2' }, components: { '/search/all': { props: payload(routerIds) } } } },
    __mcReadBaseline: { keyword: 'current', router: payload(p1) },
    __mcTap: { items },
  };
}
function tapEntry(ids, override = {}) {
  return Object.assign({ at: 6000, requestStartedAt: 5100, page: 2, keyword: 'current', status: 200,
    path: 'search.shopping.naver.com/api/search/all', sourceKnown: true, scopeVerified: true,
    responseMatched: true, json: payload(ids) }, override);
}
function extract(win, want = { keyword: 'current', page: 2, since: 5000 }) {
  const sandbox = { URL, window: win, location: loc, document: { title: 'Shopping', body: { innerText: '' } } };
  vm.runInNewContext(grab('pageExtract') + '\nresult = pageExtract(want);', Object.assign(sandbox, { want }));
  return sandbox.result;
}
async function fetchPageOffline(win) {
  const reads = [], reports = [];
  const arrived = win.next.router.components['/search/all'].props;
  win.next.router.components['/search/all'].props = payload(p1);
  const s = {
    URL, window: win, location: loc, document: { title: 'Shopping', body: { innerText: '' } }, RR,
    Date: { now: () => 5000 },
    ensureWorkTab: async () => 99, clickToPage: async () => {
      win.next.router.components['/search/all'].props = arrived;
      return true;
    },
    waitNavigated: async () => {}, sleep: async () => {}, isBlockedUrl: () => false,
    CFG: { readTries: 2, readTriesPaged: 3, readGapMs: 0 },
    _navMode: { click: 0, url: 0, stale: 0, src: {}, entry: {}, reported: false },
    _clickedAt: 0, _staleReported: false, _lastClickBranch: 'fake-success', _lastClickHow: 'trusted',
    _trustedNote: '', _clickHit: '', _clickCovered: false, _pagerAfter: '2', _entryNote: '', _entryVia: '',
    navProbe: () => ({ href: loc.href }), reportBlocked: ev => reports.push(ev), tapReport: async () => {},
  };
  s.chrome = {
    tabs: { get: async () => ({ id: 99, url: loc.href, title: 'Shopping' }) },
    scripting: { executeScript: async ({ func, args = [] }) => {
      const result = func(...args); if (func.name === 'pageExtract') reads.push(result);
      return [{ result }];
    } }, storage: { local: { set: async () => {} } },
  };
  vm.createContext(s);
  vm.runInContext([grab('pageExtract'), grab('organicIds'), grab('pageChanged'), grab('fetchPage', true)].join('\n'), s);
  const result = await s.fetchPage('current', 2, p1.map(String));
  return { result, readCount: reads.length, selected: reads.map(r => ({ src: r.src, first: r.list && r.list[0].nvMid })), reports };
}
async function captured(body, { xhr = false } = {}) {
  let now = 1000;
  let callback;
  const u = 'https://search.shopping.naver.com/api/search/all?query=current&pagingIndex=2';
  class FakeXHR {
    open() {} send() {} addEventListener(type, fn) { if (type === 'loadend') callback = fn; }
    getResponseHeader() { return 'application/json'; }
  }
  const win = { fetch: async () => ({ status: 200, url: u, headers: { get: () => 'application/json' },
    clone: () => ({ text: async () => JSON.stringify(body) }) }), XMLHttpRequest: FakeXHR };
  vm.runInNewContext(tapSrc, { window: win, location: loc, URL, Date: { now: () => now } });
  if (xhr) {
    const req = new win.XMLHttpRequest();
    req.open('GET', u); req.send(); // clock = 1000 (before page click)
    now = 6000; // clock = 6000 (after page click)
    Object.assign(req, { responseType: '', responseText: JSON.stringify(body), status: 200, responseURL: u });
    callback.call(req);
  } else {
    now = 6000;
    await win.fetch(u);
    await new Promise(resolve => setImmediate(resolve));
  }
  return win.__mcTap;
}
const results = [];
async function check(name, fn) {
  try { await fn(); results.push({ name, verdict: 'PASS' }); }
  catch (e) { results.push({ name, verdict: 'FAIL', message: e.message.split('\n')[0] }); }
}
(async () => {
  await check('control: current p2 tap reaches real fetchPage successfully', async () => {
    const got = await fetchPageOffline(scene(p1, [tapEntry(p2)]));
    assert.equal(got.result.list[0].nvMid, '41');
    assert.equal(got.result.stopReason, undefined);
  });
  await check('current router p2 must not be hidden by stale tap p2 from before click', async () => {
    const got = await fetchPageOffline(scene(p2, [tapEntry(p1, { at: 1000, requestStartedAt: 900 })]));
    console.log('OBS old-p2-shadow', JSON.stringify(got));
    assert.equal(got.result.stopReason, undefined);
    assert.equal(got.result.list[0].nvMid, '41');
  });
  await check('current p2 tap must not be hidden by later unrelated no-page recommendation', async () => {
    const got = await fetchPageOffline(scene(p1, [tapEntry(p2), tapEntry(p1, {
      at: 7000, page: 0, path: 'recommend.example/products', keyword: '', sourceKnown: false, scopeVerified: false,
    })]));
    console.log('OBS unrelated-shadow', JSON.stringify(got));
    assert.equal(got.result.stopReason, undefined);
    assert.equal(got.result.list[0].nvMid, '41');
  });
  await check('invalid response identity must not replace verified current p2 router', () => {
    const got = extract(scene(p2, [tapEntry([801], { keyword: 'other-keyword', status: 418,
      sourceKnown: false, scopeVerified: false, responseMatched: false })]));
    console.log('OBS identity-ignored', JSON.stringify({ src: got.src, first: got.list[0].nvMid }));
    assert.equal(got.list[0].nvMid, '41');
  });
  await check('reader-compatible productName/id response must survive capture and page fetch', async () => {
    const body = { products: [{ productName: 'New product', id: '41' }] };
    const direct = extract(scene(p1, [tapEntry([], { json: body })]));
    assert.equal(direct.list[0].id, '41');
    const capturedTap = await captured(body);
    const got = await fetchPageOffline(scene(p1, capturedTap.items));
    console.log('OBS marker-gap', JSON.stringify({ items: capturedTap.items.length, misses: capturedTap.misses.length, got }));
    assert.equal(got.result.stopReason, undefined);
  });
  await check('XHR requestStartedAt must reflect send time before click', async () => {
    const T = await captured(payload(p2), { xhr: true });
    console.log('OBS xhr-time', JSON.stringify({ sentAt: 1000, clickedAt: 5000, recordedAt: T.items[0].at, requestStartedAt: T.items[0].requestStartedAt }));
    assert.equal(T.items[0].requestStartedAt, 1000);
  });
  await check('URL advanced but props unchanged is not verified page 2', () => {
    const win = scene(p1, []);
    win.__mcReadBaseline.router = win.next.router.components['/search/all'].props;
    assert.equal(extract(win).err, 'UNVERIFIED_PAGE');
  });
  await check('all identity gates are enforced independently, not only in combination', () => {
    for (const bad of [{ keyword: 'other' }, { page: 3 }, { scopeVerified: false },
      { sourceKnown: false }, { responseMatched: false }, { requestStartedAt: 4999 }]) {
      const win = scene(p1, [tapEntry(p2, bad)]);
      win.__mcReadBaseline.router = win.next.router.components['/search/all'].props;
      assert.equal(extract(win).err, 'UNVERIFIED_PAGE', JSON.stringify(bad));
    }
  });
  await check('fresh restricted search response cannot fall back to older products', () => {
    for (const status of [401, 403, 418, 429]) {
      const win = scene(p2, [tapEntry(p2), tapEntry([], { status, requestStartedAt: 5500, json: null })]);
      const got = extract(win);
      assert.equal(got.err, 'HTTP_RESTRICTED');
      assert.equal(got.status, status);
    }
  });
  await check('initial hydration is usable only for its own keyword and page', () => {
    const win = { __NEXT_DATA__: Object.assign({ query: { query: 'current', pagingIndex: '2' } }, payload(p2)) };
    assert.equal(extract(win).list[0].nvMid, '41');
    win.__NEXT_DATA__.query.pagingIndex = '1';
    assert.equal(extract(win).err, 'UNVERIFIED_PAGE');
  });
  await check('unchanged SSR snapshot must not become a new observation', () => {
    const nd = Object.assign({ query: { query: 'current', pagingIndex: '2' } }, payload(p2));
    const win = { __NEXT_DATA__: nd, __mcReadBaseline: { keyword: 'current', nextdata: nd } };
    assert.equal(extract(win).err, 'UNVERIFIED_PAGE');
  });
  await check('reused XHR records once per send and preserves the original return value', () => {
    let now = 1000, sends = 0;
    class XHR extends EventTarget {
      open() {} send() { sends++; return 'native-return'; }
      getResponseHeader() { return 'application/json'; }
    }
    const win = { XMLHttpRequest: XHR };
    vm.runInNewContext(tapSrc, { window: win, location: loc, URL, Date: { now: () => now } });
    const x = new XHR();
    for (const page of [2, 3]) {
      const u = 'https://search.shopping.naver.com/api/search/all?query=current&pagingIndex=' + page;
      x.open('GET', u); assert.equal(x.send(), 'native-return');
      now += 100;
      Object.assign(x, { responseType: '', responseText: JSON.stringify(payload(p2)), responseURL: u, status: 200 });
      x.dispatchEvent(new Event('loadend'));
    }
    assert.equal(sends, 2); assert.equal(win.__mcTap.items.length, 2);
    assert.deepEqual(Array.from(win.__mcTap.items, it => it.requestStartedAt), [1000, 1100]);
    assert.notEqual(win.__mcTap.items[0].requestId, win.__mcTap.items[1].requestId);
  });
  console.log(JSON.stringify({ baseline: '60864fbe (1.27.0)', tested: 'current working tree', results }, null, 2));
  process.exitCode = results.some(r => r.verdict === 'FAIL') ? 1 : 0;
})().catch(e => { console.error(e); process.exitCode = 2; });
