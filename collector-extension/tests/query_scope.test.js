// Offline regression for the navigation metadata observed in server diagnostics.
// Executes production readers/tap with fake boundaries; sends no network requests.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
const tapSource = fs.readFileSync(path.join(__dirname, '../net_tap.js'), 'utf8');
function grab(name) {
  const start = source.indexOf('function ' + name + '(');
  assert(start >= 0);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('Unclosed ' + name);
}
const keyword = '시험 검색어';
const params = page => new URLSearchParams({ query: keyword, pagingIndex: String(page) }).toString();
const body = page => ({ products: Array.from({ length: 40 }, (_, i) => ({
  nvMid: String((page - 1) * 40 + i + 1), productTitle: 'Fixture', mallName: 'Fixture',
})) });
function read({ page = 1, suffix = '', route = 'tap', queryExtra = {}, stale = false, implicitFirstPage = false, tapEntry } = {}) {
  const url = new URL('https://search.shopping.naver.com/search/all?' + params(page) + suffix);
  const query = { query: keyword, pagingIndex: String(page), ...queryExtra };
  if (implicitFirstPage) { url.searchParams.delete('pagingIndex'); delete query.pagingIndex; }
  const current = body(page), before = body(1);
  const win = route === 'tap' ? { __mcTap: { items: [tapEntry || {
    at: 6000, requestStartedAt: stale ? 4999 : 5100, page, keyword, status: 200,
    sourceKnown: true, scopeVerified: true, responseMatched: true, json: current,
    path: 'search.shopping.naver.com/api/search/all',
  }] } } : route === 'router' ? {
    next: { router: { route: '/search/all', query, components: { '/search/all': { props: current } } } },
    __mcReadBaseline: { keyword, router: stale ? current : before },
  } : {
    __NEXT_DATA__: { query, ...current },
  };
  if (stale && route === 'nextdata') win.__mcReadBaseline = { keyword, nextdata: win.__NEXT_DATA__ };
  const sandbox = { URL, window: win, location: url,
    document: { title: 'Fixture shopping', body: { innerText: 'Normal product list' } },
    want: { keyword, page, since: 5000 } };
  vm.runInNewContext(grab('pageExtract') + '\nresult = pageExtract(want);', sandbox);
  return sandbox.result;
}
async function capture(requestSuffix = '', responseSuffix = requestSuffix, xhr = false, { status = 200, startedAt = 5100 } = {}) {
  const requestUrl = 'https://search.shopping.naver.com/api/search/all?' + params(2) + requestSuffix;
  const responseUrl = 'https://search.shopping.naver.com/api/search/all?' + params(2) + responseSuffix;
  let listener;
  class XHR {
    open() {} send() {}
    addEventListener(type, fn) { if (type === 'loadend') listener = fn; }
    getResponseHeader() { return 'application/json'; }
  }
  let requests = 0;
  const win = { XMLHttpRequest: XHR, fetch: async () => {
    requests++;
    return { status, url: responseUrl, headers: { get: () => 'application/json' },
      clone: () => ({ text: async () => JSON.stringify(body(2)) }) };
  } };
  vm.runInNewContext(tapSource, { URL, window: win,
    location: new URL('https://search.shopping.naver.com/search/all?' + params(2)), Date: { now: () => startedAt } });
  if (xhr) {
    const req = new win.XMLHttpRequest(); req.open('GET', requestUrl); req.send();
    Object.assign(req, { responseType: '', responseText: JSON.stringify(body(2)), status, responseURL: responseUrl });
    listener.call(req);
  } else {
    await win.fetch(requestUrl);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests, 1, 'tap must not add requests');
  }
  assert.equal(win.__mcTap.items.length, 1);
  return win.__mcTap.items[0];
}
const observed = '&prevQuery=previous&vertical=search';
test('observed empty timestamp reaches the real page-2 reader through fetch capture', async () => {
  // Same ten-key URL shape as the field report; search values are synthetic.
  const suffix = '&' + new URLSearchParams({ adQuery: keyword, frm: 'FIXTURE', origQuery: keyword,
    pagingSize: '40', productSet: 'total', sort: 'rel', viewType: 'list', timestamp: '' });
  const entry = await capture(suffix);
  const result = read({ page: 2, suffix, tapEntry: entry });
  assert.equal(result.err, undefined);
  assert.equal(result.list.length, 40);
  assert.equal(result.list[0].nvMid, '41');
  assert.equal(result.pageIndex, 2);
  assert.equal(result.verified, true);
});
test('empty timestamp is accepted independently on location, request and response for fetch and XHR', async () => {
  for (const xhr of [false, true]) for (const locationSuffix of ['', '&timestamp=']) {
    for (const requestSuffix of ['', '&timestamp=']) for (const responseSuffix of ['', '&timestamp=']) {
      const entry = await capture(requestSuffix, responseSuffix, xhr);
      const result = read({ page: 2, suffix: locationSuffix, tapEntry: entry });
      assert.equal(result.err, undefined);
      assert.equal(result.list[0].nvMid, '41');
      assert.equal(result.src, 'tap');
    }
  }
});
test('only a single empty timestamp is metadata, not nonempty, duplicated or unknown scope', async () => {
  for (const bad of ['&timestamp=0', '&timestamp=1790928000000', '&timestamp=undefined', '&timestamp=%20',
    '&timestamp=%00', '&timestamp=&timestamp=', '&timestamp=&%74imestamp=', '&timestamp[]=',
    '&timestamp=&filter=organic', '&timestamp=&sort=price', '&timestamp=&pagingSize=80',
    '&timestamp=&productSet=brand', '&timestamp=&vertical=other', '&timestamp=&where=shop',
    '&timestamp=&query=other', '&timestamp=&pagingIndex=1']) {
    assert.equal(read({ page: 2, suffix: bad }).err, 'UNVERIFIED_PAGE', bad);
    for (const xhr of [false, true]) {
      assert.equal((await capture(bad, bad, xhr)).scopeVerified, false, bad);
      const entry = await capture('&timestamp=', bad, xhr);
      assert.equal(entry.responseMatched, false, bad);
      assert.equal(read({ page: 2, suffix: '&timestamp=', tapEntry: entry }).err, 'UNVERIFIED_PAGE', bad);
    }
  }
});
test('empty timestamp preserves router and hydration identity and staleness checks', () => {
  for (const route of ['router', 'nextdata']) for (const page of [1, 2]) {
    const args = { route, page, suffix: '&timestamp=', queryExtra: { timestamp: '' } };
    assert.equal(read(args).list[0].nvMid, String((page - 1) * 40 + 1));
    assert.equal(read({ ...args, stale: true }).err, 'UNVERIFIED_PAGE');
    for (const timestamp of [null, false, 0, [], [''], ['',''], {}, '0', ' ']) {
      assert.equal(read({ ...args, queryExtra: { timestamp } }).err, 'UNVERIFIED_PAGE');
    }
    for (const extra of [{ query: 'other' }, { pagingIndex: String(page + 1) }, { filter: 'organic' }]) {
      assert.equal(read({ ...args, queryExtra: { timestamp: '', ...extra } }).err, 'UNVERIFIED_PAGE');
    }
  }
});
test('empty timestamp cannot revive old captures or hide a fresh HTTP restriction', async () => {
  for (const xhr of [false, true]) {
    const stale = await capture('&timestamp=', '&timestamp=', xhr, { startedAt: 4999 });
    assert.equal(read({ page: 2, suffix: '&timestamp=', tapEntry: stale }).err, 'UNVERIFIED_PAGE');
    for (const status of [401, 403, 418, 429, 500]) {
      const entry = await capture('&timestamp=', '&timestamp=', xhr, { status });
      const result = read({ page: 2, suffix: '&timestamp=', tapEntry: entry });
      assert.equal(result.err, status === 500 ? 'HTTP_ERROR' : 'HTTP_RESTRICTED');
      assert.equal(result.status, status);
      assert.equal(result.list, undefined);
    }
    for (const changed of [{ keyword: 'other' }, { page: 1 }, { sourceKnown: false }]) {
      const entry = await capture('&timestamp=', '&timestamp=', xhr);
      assert.equal(read({ page: 2, suffix: '&timestamp=', tapEntry: { ...entry, ...changed } }).err, 'UNVERIFIED_PAGE');
    }
  }
});
test('portal shopping entry where=all is accepted without changing ranking scope', async () => {
  for (const route of ['tap', 'router', 'nextdata']) {
    const result = read({ route, implicitFirstPage: true, suffix: '&where=all&frm=NVSCTAB',
      queryExtra: { where: 'all', frm: 'NVSCTAB' } });
    assert.equal(result.err, undefined, route);
    assert.equal(result.list.length, 40);
  }
  for (const xhr of [false, true]) {
    const entry = await capture('&where=all&frm=NVSCTAB', '&where=all&frm=NVSCTAB', xhr);
    assert.equal(entry.scopeVerified, true);
    assert.equal(entry.responseMatched, true);
  }
});
test('portal metadata never permits another vertical, duplicated parameters or filters', async () => {
  for (const bad of ['&where=', '&where=shop', '&where=ALL', '&where=all&where=all',
    '&where=all&%77here=all', '&where=all&spec=M10014366', '&where=all&filter=organic']) {
    assert.equal(read({ suffix: bad }).err, 'UNVERIFIED_PAGE', bad);
    assert.equal((await capture(bad)).scopeVerified, false, bad);
    assert.equal((await capture('&where=all', bad)).responseMatched, false, bad);
  }
  for (const route of ['router', 'nextdata']) for (const where of ['', 'shop', ['all'], null, false]) {
    assert.equal(read({ route, suffix: '&where=all', queryExtra: { where } }).err,
      'UNVERIFIED_PAGE', JSON.stringify({ route, where }));
  }
  for (const route of ['tap', 'router', 'nextdata']) {
    assert.equal(read({ route, suffix: '&where=all', queryExtra: { where: 'all' }, stale: true }).err,
      'UNVERIFIED_PAGE', route);
  }
});
test('observed navigation metadata permits fresh p1 and p2 evidence from each source', () => {
  for (const page of [1, 2]) for (const route of ['tap', 'router', 'nextdata']) {
    const result = read({ page, route, suffix: observed, queryExtra: { prevQuery: 'previous', vertical: 'search' } });
    assert.equal(result.err, undefined, `${route} p${page}`);
    assert.equal(result.list.length, 40);
    assert.equal(result.list[0].nvMid, String((page - 1) * 40 + 1));
    assert.equal(result.src, route);
  }
});
test('each metadata field independently accepted, previous query is not current query identity', () => {
  for (const suffix of ['', '&prevQuery=unrelated', '&prevQuery=', '&vertical=search', observed]) {
    assert.equal(read({ suffix }).list.length, 40, suffix);
  }
});
test('observed first-page URL without pagingIndex still reads fresh matching data', () => {
  for (const route of ['tap', 'router', 'nextdata']) {
    const result = read({ route, suffix: observed, implicitFirstPage: true,
      queryExtra: { prevQuery: 'previous', vertical: 'search' } });
    assert.equal(result.err, undefined, route);
    assert.equal(result.list.length, 40);
    assert.equal(result.list[0].nvMid, '1');
  }
});
test('unknown, duplicate and non-search scope still reject live location', () => {
  for (const suffix of ['&vertical=other', '&vertical=', '&vertical=search&vertical=search',
    '&%76ertical=search&vertical=search', '&prev%51uery=a&prevQuery=b',
    '&prevQuery=a&prevQuery=b', '&filter=organic', '&sort=price', '&productSet=brand',
    '&pagingSize=80', '&query=other', '&pagingIndex=2']) {
    assert.equal(read({ suffix }).err, 'UNVERIFIED_PAGE', suffix);
  }
});
test('router and hydration metadata do not weaken query or scope identity', () => {
  for (const route of ['router', 'nextdata']) for (const queryExtra of [
    { query: 'different' }, { pagingIndex: '2' }, { vertical: 'other' }, { vertical: '' },
    { vertical: ['search'] }, { prevQuery: ['a', 'b'] }, { filter: 'organic' }, { sort: 'price' },
  ]) assert.equal(read({ route, suffix: observed, queryExtra }).err, 'UNVERIFIED_PAGE', JSON.stringify({ route, queryExtra }));
});
test('permitted metadata never revives stale tap, router or hydration data', () => {
  for (const route of ['tap', 'router', 'nextdata']) assert.equal(read({ route, suffix: observed,
    queryExtra: { prevQuery: 'previous', vertical: 'search' }, stale: true }).err, 'UNVERIFIED_PAGE', route);
});
test('fetch and XHR capture accept observed search metadata without additional requests', async () => {
  for (const xhr of [false, true]) {
    const entry = await capture(observed, observed, xhr);
    assert.equal(entry.sourceKnown, true);
    assert.equal(entry.scopeVerified, true);
    assert.equal(entry.responseMatched, true);
    assert.equal(entry.keyword, keyword);
    assert.equal(entry.page, 2);
  }
});
test('capture rejects changed request or response scope and duplicate metadata', async () => {
  for (const bad of ['&vertical=other', '&vertical=', '&vertical=search&vertical=search',
    '&prevQuery=a&prevQuery=b', '&filter=organic', '&sort=price', '&productSet=brand', '&pagingSize=80']) {
    assert.equal((await capture(bad)).scopeVerified, false, bad);
    const entry = await capture(observed, bad);
    assert.equal(entry.scopeVerified, true);
    assert.equal(entry.responseMatched, false, bad);
  }
});
test('metadata can be dropped or changed on a response without changing its search identity', async () => {
  for (const xhr of [false, true]) for (const [sent, received] of [
    [observed, ''], ['', observed], [observed, '&prevQuery=different&vertical=search'],
  ]) {
    const entry = await capture(sent, received, xhr);
    assert.equal(entry.scopeVerified, true);
    assert.equal(entry.responseMatched, true);
  }
});
