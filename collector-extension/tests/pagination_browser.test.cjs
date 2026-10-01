// Isolated Chromium fixture. Every HTTP request is fulfilled locally; no live shopping traffic.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');
const source = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
const tap = fs.readFileSync(path.join(__dirname, '../net_tap.js'), 'utf8');
const RR = require('../rank_rules.js');
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
const products = page => Array.from({ length: 40 }, (_, i) => ({ nvMid: String((page - 1) * 40 + i + 1), productTitle: 'Fixture', mallName: 'Fixture' }));
(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.COLLECTOR_TEST_CHANNEL || undefined });
  try {
    const cases = ['tap', 'router', 'restricted', 'covered', 'group-next'].map(mode => ({ mode, metadata: false }))
      .concat(['tap', 'router', 'restricted'].map(mode => ({ mode, metadata: true })))
      .concat(['tap', 'router', 'restricted'].map(mode => ({ mode, metadata: 'portal' })))
      .concat([{ mode: 'tap', metadata: true, decoy: true },
        { mode: 'tap', metadata: 'portal', decoy: true, unmarked: true },
        { mode: 'tap', metadata: 'portal', actualSmooth: true }]);
    for (const { mode, metadata, decoy, unmarked, actualSmooth } of cases) {
      const query = { query: 'fixture', ...(metadata === 'portal' ? { where: 'all', frm: 'NVSCTAB' }
        : metadata ? { prevQuery: 'previous', vertical: 'search' } : {}) };
      const url = 'https://search.shopping.naver.com/search/all?' + new URLSearchParams(query);
      const context = await browser.newContext();
      const page = await context.newPage();
      let searchRequests = 0;
      await context.route('**/*', async route => {
        const u = new URL(route.request().url());
        if (u.pathname === '/api/search/all') {
          searchRequests++;
          await new Promise(resolve => setTimeout(resolve, 800));
          return route.fulfill({ status: mode === 'restricted' ? 418 : 200, contentType: 'application/json',
            body: JSON.stringify(mode === 'restricted' ? { error: 'restricted' } : { products: products(2) }) });
        }
        if (u.href === url) return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<main>
          ${decoy ? '<section role="navigation"><a id="filter" href="#">2</a></section>' : ''}
          <nav role="navigation"><span class="active">1</span>
          ${mode === 'group-next' ? '<a class="next" href="?query=fixture&pagingIndex=11">Next</a>'
            : unmarked ? '<a href="?' + new URLSearchParams({ ...query, pagingIndex: '2' }) + '">2</a>'
            : '<a href="#" data-shp-area="prd_pgn.pgn" data-shp-contents-id="2">2</a>'}
          </nav></main><style>nav{margin:40px}a{display:inline-block;padding:20px}</style>` });
        return route.abort();
      });
      await page.addInitScript({ content: tap });
      await page.goto(url);
      await page.evaluate(({ first, second, mode, query, actualSmooth }) => {
        window.clicks = 0;
        window.filterClicks = 0;
        const filter = document.querySelector('#filter');
        if (filter) filter.addEventListener('click', e => {
          e.preventDefault(); window.filterClicks++;
          history.pushState({}, '', '?query=fixture&pagingIndex=1&spec=FILTER');
        });
        window.__NEXT_DATA__ = { query: { ...query }, props: { products: first } };
        window.next = { router: { route: '/search/all', query: { ...query, pagingIndex: '1' },
          components: { '/search/all': { props: { products: first } } } } };
        if (actualSmooth) {
          document.documentElement.style.scrollBehavior = 'smooth';
          document.body.style.height = '6500px';
          document.querySelector('nav').style = 'position:absolute;top:5500px';
        }
        document.querySelector('nav a').addEventListener('click', async e => {
          e.preventDefault(); window.clicks++;
          let data;
          if (mode === 'router') { await new Promise(r => setTimeout(r, 800)); data = { products: second }; }
          else { const res = await fetch('/api/search/all?' + new URLSearchParams({ ...query, pagingIndex: '2' })); if (!res.ok) return; data = await res.json(); }
          history.pushState({}, '', '?' + new URLSearchParams({ ...query, pagingIndex: '2' }));
          window.next.router.query.pagingIndex = '2';
          if (mode === 'router') window.next.router.components['/search/all'].props = data;
          document.querySelector('span').textContent = '2';
        });
        if (mode === 'covered') {
          const cover = document.createElement('div'); cover.style = 'position:fixed;inset:0;background:white;z-index:1000';
          cover.textContent = 'Overlay'; document.body.appendChild(cover);
        }
      }, { first: products(1), second: products(2), mode, query, actualSmooth });
      const cdp = await context.newCDPSession(page);
      const store = {}, reports = [];
      const sandbox = {
        URL, RR, crypto: require('node:crypto').webcrypto, Date, Math, Set, setTimeout, clearTimeout,
        CFG: { maxRank: 80, pagesPerKeyword: 2, maxPages: 2, readTries: 2, readTriesPaged: 20, readGapMs: 100 },
        RT: actualSmooth ? require('../remote_settings.js').merge({}).values : {},
        EVIDENCE_SOURCES: new Set(['tap', 'router', 'nextdata']),
        _navMode: { reported: false }, _clickedAt: 0, _staleReported: false, _lastClickBranch: '', _lastClickHow: '',
        _trustedNote: '', _clickHit: '', _clickCovered: 0, _pagerAfter: '', _entryNote: '', _entryVia: '',
        ensureWorkTab: async () => 1, searchEntryEnabled: async () => false,
        instanceId: async () => 'fixture-worker', targetsFor: () => null,
        isBlockedUrl: () => false, jitter: () => 0, trustedEnabled: async () => true,
        waitNavigated: async () => {}, humanScrollDown: async () => {},
        dbgAttach: async () => {}, dbgDetach: async () => {},
        dbgSend: (_id, command, params) => cdp.send(command, params),
        sleep: ms => new Promise(r => setTimeout(r, ms)),
        reportBlocked: data => reports.push(data), tapReport: async () => {},
      };
      sandbox.chrome = { debugger: {}, storage: { local: { get: async () => ({}), set: async data => Object.assign(store, data) } },
        tabs: { update: async () => page.evaluate(() => { window.__NEXT_DATA__ = JSON.parse(JSON.stringify(window.__NEXT_DATA__)); }),
          get: async () => ({ url: page.url(), title: 'Fixture' }) },
        scripting: { executeScript: async ({ func, args = [] }) => [{ result: await page.evaluate(
          ({ fn, args }) => (0, eval)('(' + fn + ')')(...args), { fn: func.toString(), args }) }] } };
      vm.createContext(sandbox);
      vm.runInContext(['pageExtract','organicIds','pageChanged','pagerLocate','pagerClick','pagerState','readPagerState',
        'pagerGuardCall','trustedClickToPage','clickToPage','navProbe','fetchPage','collectKeyword'].map(grab).join('\n'), sandbox);
      if (actualSmooth) vm.runInContext(['scrollStep','humanScrollDown'].map(grab).join('\n'), sandbox);
      const result = await sandbox.collectKeyword('fixture');
      // Feed the actual extension envelope into the actual Python validation + ledger module.
      const ledger = spawnSync(process.env.COLLECTOR_TEST_PYTHON || 'python3', ['-c', `
import sys, json, sqlite3
sys.path.insert(0, 'backend')
import collector_observation as co
item = co.validate(json.load(sys.stdin))
conn = sqlite3.connect(':memory:')
co.init_observation_db(conn)
calls = []
def full(positive_only):
    calls.append('full_positive' if positive_only else 'full')
    return {}
def positive():
    calls.append('positive')
    return {}
co.ingest(conn, item, '2026-09-30', full, positive)
print(json.dumps({'kind': item['kind'], 'calls': calls, 'rows': conn.execute('SELECT COUNT(*) FROM collector_observations').fetchone()[0]}))
`], { cwd: path.join(__dirname, '../..'), encoding: 'utf8', input: JSON.stringify({ keyword: 'fixture', products: result.products,
        total: result.total, meta: { observation: result.observation } }) });
      assert.equal(ledger.status, 0, ledger.stderr);
      const saved = JSON.parse(ledger.stdout);
      assert.equal(saved.rows, 1);
      assert.equal(saved.kind, ['tap', 'router'].includes(mode) ? 'full' : 'positive');
      assert.deepEqual(saved.calls, [['tap', 'router'].includes(mode) ? 'full' : 'positive']);
      const clicks = await page.evaluate(() => window.clicks);
      assert.equal(await page.evaluate(() => window.filterClicks), 0, 'numeric filter must never be clicked');
      if (['tap', 'router'].includes(mode)) {
        assert.equal(result.products.length, 80, JSON.stringify(result.observation));
        assert.equal(result.products[40].rank, 41);
        assert.equal(result.products[40].nvMid, '41');
        assert.equal(result.products[40].sourcePage, 2);
        assert.equal(result.observation.status, 'complete');
        assert.equal(result.observation.pagesAttempted, 2);
        assert.equal(clicks, 1);
        assert.equal(searchRequests, mode === 'tap' ? 1 : 0);
      } else {
        assert.equal(result.products.length, 40);
        assert.equal(result.observation.status, 'partial');
        assert.equal(result.observation.pagesRead, 1);
        if (mode === 'restricted') {
          assert.equal(result.observation.stopReason, 'BLOCKED');
          assert.equal(searchRequests, 1); assert.equal(clicks, 1);
          assert(reports.some(r => r.err === 'HTTP_418'));
        } else { assert.equal(clicks, 0); assert.equal(searchRequests, 0); }
      }
      console.log('PASS browser ' + mode + (metadata === 'portal' ? '-portal' : metadata ? '-metadata' : '')
        + (decoy ? unmarked ? '-decoy-href' : '-decoy-marked' : '')
        + (actualSmooth ? '-actual-smooth-scroll' : '')
        + ': ' + result.products.length + ' ranks, clicks=' + clicks + ', requests=' + searchRequests);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
