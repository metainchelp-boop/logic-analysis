// Offline wrong-target browser regression; actual production functions and fully intercepted Chromium.
// Run: NODE_PATH=<bundled node_modules> COLLECTOR_TEST_CHANNEL=chrome node --test collector-extension/tests/pager_target_browser.test.cjs
'use strict';
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
test('actual trusted Chrome click must not activate a numeric filter', async () => {
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ headless: true, channel: process.env.COLLECTOR_TEST_CHANNEL || 'chrome' });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    let requests = 0;
    const url = 'https://search.shopping.naver.com/search/all?query=fixture&prevQuery=previous&vertical=search';
    await context.route('**/*', route => {
      requests++;
      if (route.request().url() === url) return route.fulfill({ contentType: 'text/html',
        body: '<style>a{display:inline-block;margin:40px;padding:20px}</style><a id="filter" href="#">2</a>' });
      return route.abort();
    });
    await page.goto(url);
    await page.evaluate(() => {
      window.filterClicks = 0;
      document.querySelector('#filter').addEventListener('click', e => {
        e.preventDefault(); window.filterClicks++;
        history.pushState({}, '', '?query=fixture&prevQuery=previous&vertical=search&pagingIndex=1&spec=M10014366%7CM10771206');
      });
    });
    const cdp = await context.newCDPSession(page);
    const sandbox = {
      Date, Math, _trustedNote: '', _clickHit: '', _clickCovered: 0, _pagerAfter: '', _clickedAt: 0,
      dbgAttach: async () => {}, dbgDetach: async () => {}, humanScrollDown: async () => {},
      readPagerState: async () => {}, sleep: async () => {},
      dbgSend: (_tab, command, params) => cdp.send(command, params),
      chrome: { debugger: {}, scripting: { executeScript: async ({ func, args }) => [{ result: await page.evaluate(
        ({ code, args }) => (0, eval)('(' + code + ')')(...args), { code: func.toString(), args }) }] } },
    };
    vm.createContext(sandbox);
    vm.runInContext(grab('pagerLocate') + '\n' + grab('trustedClickToPage'), sandbox);
    const branch = await sandbox.trustedClickToPage(1, 2);
    const filterClicks = await page.evaluate(() => window.filterClicks);
    console.log('OBS actual-browser', JSON.stringify({ branch, filterClicks, url: page.url(), requests, hit: sandbox._clickHit }));
    assert.equal(filterClicks, 0, 'Page-2 request activated a filter instead');
    assert.equal(branch, '');
  } finally { await browser.close(); }
});
test('real browser: both input paths choose genuine marker or validated link exactly once', async () => {
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ headless: true, channel: process.env.COLLECTOR_TEST_CHANNEL || 'chrome' });
  try {
    for (const mode of ['trusted', 'synthetic']) for (const kind of ['marker', 'href', 'covered']) {
      const context = await browser.newContext();
      const page = await context.newPage();
      let requests = 0;
      const url = 'https://search.shopping.naver.com/search/all?query=fixture&where=all&vertical=search';
      await context.route('**/*', route => {
        requests++;
        if (route.request().url() !== url) return route.abort();
        const attrs = kind === 'href' ? 'href="?query=fixture&pagingIndex=2&where=all&vertical=search"'
          : 'href="#" data-shp-area="prd_pgn.pgn" data-shp-contents-id="2"';
        return route.fulfill({ contentType: 'text/html', body: '<style>a{display:inline-block;margin:30px;padding:20px}</style>'
          + '<nav role="navigation"><a id="filter" href="#">2</a><a id="wrong" href="?query=fixture&pagingIndex=1&spec=M10014366">2</a>'
          + '<a id="pager" ' + attrs + '>2</a></nav>' });
      });
      await page.goto(url);
      await page.evaluate(covered => {
        window.clicks = [];
        for (const el of document.querySelectorAll('a')) el.addEventListener('click', e => {
          e.preventDefault(); window.clicks.push(el.id);
        });
        if (covered) {
          const overlay = document.createElement('div');
          overlay.style = 'position:fixed;inset:0;z-index:10;background:white'; document.body.appendChild(overlay);
        }
      }, kind === 'covered');
      const cdp = await context.newCDPSession(page);
      const sandbox = {
        Date, Math, _trustedNote: '', _clickHit: '', _clickCovered: 0, _pagerAfter: '', _clickedAt: 0,
        dbgAttach: async () => {}, dbgDetach: async () => {}, humanScrollDown: async () => {},
        readPagerState: async () => {}, sleep: async () => {},
        dbgSend: (_tab, command, params) => cdp.send(command, params),
        chrome: { debugger: {}, scripting: { executeScript: async ({ func, args }) => [{ result: await page.evaluate(
          ({ code, args }) => (0, eval)('(' + code + ')')(...args), { code: func.toString(), args }) }] } },
      };
      vm.createContext(sandbox);
      vm.runInContext(grab('pagerLocate') + '\n' + grab('trustedClickToPage'), sandbox);
      if (mode === 'trusted') await sandbox.trustedClickToPage(1, 2);
      else await page.evaluate(code => (0, eval)('(' + code + ')')(2), grab('pagerClick'));
      assert.deepEqual(await page.evaluate(() => window.clicks), kind === 'covered' ? [] : ['pager'], mode + '/' + kind);
      assert.equal(requests, 1, 'only locally fulfilled fixture document requested');
      await context.close();
    }
  } finally { await browser.close(); }
});
