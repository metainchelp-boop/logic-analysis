'use strict';
// Real Chrome input + actual production scrolling/click entry point. HTTP is local-only.
// Run: NODE_PATH=<bundled node_modules> COLLECTOR_TEST_CHANNEL=chrome node --test collector-extension/tests/click_stability_browser.test.cjs
// This does not install the extension or validate Windows/site behavior.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const RS = require('../remote_settings.js');
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

async function listenerSummary(cdp) {
  const summary = [];
  for (const expression of ['document', 'window']) {
    const { result } = await cdp.send('Runtime.evaluate', { expression });
    const { listeners } = await cdp.send('DOMDebugger.getEventListeners', { objectId: result.objectId });
    summary.push(...listeners.map(listener => expression + ':' + listener.type + ':' + listener.useCapture));
    await cdp.send('Runtime.releaseObject', { objectId: result.objectId });
  }
  return summary.sort();
}

async function scenario(kind) {
  const browser = await chromium.launch({ headless: true, channel: process.env.COLLECTOR_TEST_CHANNEL || 'chrome' });
  try {
    const context = await browser.newContext({ viewport: { width: 1200, height: 720 }, serviceWorkers: 'block' });
    const url = 'https://search.shopping.naver.com/search/all?query=fixture&pagingIndex=1&where=all&vertical=search';
    let fulfilled = 0, aborted = 0;
    await context.route('**/*', route => {
      if (route.request().url() !== url) { aborted++; return route.abort(); }
      fulfilled++;
      return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
        <style>html,body{margin:0}body{height:6500px;overflow-anchor:none}
        #pager{position:absolute;left:300px;top:5500px;width:50px;height:30px;display:block;background:#cde}</style>
        <nav role="navigation"><span aria-current="page">1</span>
        <a id="pager" href="#" data-shp-area="prd_pgn.pgn" data-shp-contents-id="2">2</a></nav>
        <script id="__NEXT_DATA__" type="application/json">{"page":1}</script>` });
    });
    const page = await context.newPage();
    await page.goto(url);
    await page.evaluate(kind => {
      window.fixtureClicks = 0;
      window.fixtureChanges = 0;
      window.fixtureEvents = [];
      if (kind === 'smooth') document.documentElement.style.scrollBehavior = 'smooth';
      // Browser timing boundary only: emulate no animation frames, as a throttled document can do.
      if (kind === 'no-frames') {
        window.requestAnimationFrame = () => 1;
        window.cancelAnimationFrame = () => {};
      }
      const pager = document.querySelector('#pager');
      if (kind === 'covered') {
        const overlay = document.createElement('div');
        overlay.id = 'cover';
        overlay.style = 'position:fixed;inset:0;z-index:10;background:white';
        document.body.appendChild(overlay);
      }
      if (kind === 'unstable') pager.animate([
        { transform: 'translateX(0)' }, { transform: 'translateX(120px)' },
      ], { duration: 200, iterations: Infinity, direction: 'alternate' });
      if (kind === 'layout-on-move') pager.addEventListener('pointermove', () => {
        pager.style.top = '5620px';
        window.fixtureChanges++;
      }, { once: true });
      for (const type of ['pointermove', 'mousedown', 'mouseup', 'click']) {
        document.addEventListener(type, event => {
          window.fixtureEvents.push({ type, target: event.target.id || event.target.tagName,
            trusted: event.isTrusted, x: event.clientX, y: event.clientY,
            pagerTop: pager.getBoundingClientRect().top });
        }, true);
      }
      function activate(event) {
        event.preventDefault();
        window.fixtureClicks++;
        history.pushState({}, '', '?query=fixture&pagingIndex=2&where=all&vertical=search');
        document.querySelector('[aria-current]').textContent = '2';
        document.querySelector('#__NEXT_DATA__').textContent = '{"page":2}';
      }
      pager.addEventListener('click', activate);
      if (kind === 'replace-on-press') pager.addEventListener('mousedown', () => {
        const replacement = pager.cloneNode(true);
        replacement.addEventListener('click', activate);
        pager.replaceWith(replacement);
        window.fixtureChanges++;
      }, { once: true });
    }, kind);
    const observerProbe = await context.newCDPSession(page);
    const listenersBefore = await listenerSummary(observerProbe);
    let cdp;
    const commands = [], scrollSteps = [], scriptCalls = [];
    function apiError(callback, message) {
      chrome.runtime.lastError = { message };
      callback();
      chrome.runtime.lastError = undefined;
    }
    const chrome = {
      runtime: { lastError: undefined },
      storage: { local: { get: async () => ({}) } },
      debugger: {
        attach(_target, _version, callback) {
          if (kind === 'attach-error') return apiError(callback, 'fixture-debugger-in-use');
          context.newCDPSession(page).then(session => { cdp = session; callback(); },
            error => apiError(callback, error.message));
        },
        sendCommand(_target, method, params, callback) {
          commands.push({ method, ...params });
          cdp.send(method, params).then(result => {
            if (kind === 'press-error' && params.type === 'mousePressed') {
              apiError(callback, 'fixture-press-reply-error');
            } else if (kind === 'release-error' && params.type === 'mouseReleased') {
              apiError(callback, 'fixture-release-reply-error');
            } else callback(result);
          }, error => apiError(callback, error.message));
        },
        detach(_target, callback) { cdp.detach().then(callback, error => apiError(callback, error.message)); },
      },
      scripting: { executeScript: async ({ func, args = [] }) => {
        scriptCalls.push(func.name);
        if (kind === 'script-error' && func.name === 'pagerLocate' && args[1]?.phase === 'start') {
          throw Error('fixture-scripting-rejected');
        }
        const result = await page.evaluate(({ code, args }) => (0, eval)('(' + code + ')')(...args),
          { code: func.toString(), args });
        // The page really installed its observer, but Chrome's reply never reaches the worker.
        if (kind === 'script-reply-lost' && func.name === 'pagerLocate' && args[1]?.phase === 'start') {
          return new Promise(() => {});
        }
        if (func.name === 'scrollStep') scrollSteps.push(result);
        return [{ result }];
      } },
    };
    const sandbox = {
      chrome, Date, setTimeout, clearTimeout,
      Math: Object.assign(Object.create(Math), { random: () => 0.5 }),
      RT: RS.merge({}).values,
      _trustedNote: '', _clickHit: '', _clickCovered: 0, _pagerAfter: '', _clickedAt: 0,
      _clickProof: null, _lastClickBranch: '', _lastClickHow: '', _navMode: { how: { trusted: 0, synth: 0 } },
    };
    const functions = ['sleep', 'scrollStep', 'humanScrollDown', 'pagerState', 'readPagerState',
      'dbgAttach', 'dbgSend', 'dbgDetach', 'pagerLocate', 'pagerClick', 'trustedEnabled',
      'trustedClickToPage', 'clickToPage'];
    if (source.includes('function pagerGuardCall(')) functions.push('pagerGuardCall');
    vm.createContext(sandbox);
    // Use the production sleep implementation and its real timer primitive, without shortening waits.
    vm.runInContext(source.match(/^const _rawSleep = .*;$/m)[0] + '\n'
      + source.match(/^const KEEPALIVE_TICK_MS = [^;]+;/m)[0] + '\n'
      + functions.map(grab).join('\n'), sandbox);
    const accepted = await sandbox.clickToPage(1, 2);
    const result = await page.evaluate(() => ({ clicks: window.fixtureClicks, changes: window.fixtureChanges, events: window.fixtureEvents,
      page: JSON.parse(document.querySelector('#__NEXT_DATA__').textContent).page }));
    assert.deepEqual(await listenerSummary(observerProbe), listenersBefore,
      'document/window observers must be removed before clickToPage returns');
    await observerProbe.detach();
    assert.equal(fulfilled, 1, 'fixture HTML must be locally fulfilled');
    assert.equal(aborted, 0, 'fixture should not attempt any additional HTTP');
    assert.equal(scrollSteps.length, kind === 'attach-error' ? 0 : 8,
      'run the actual eight production scroll steps after debugger attachment');
    assert.equal(scriptCalls.filter(name => name === 'pagerClick').length, kind === 'attach-error' ? 1 : 0,
      'only confirmed debugger attach failure may enter the synthetic fallback');
    return { accepted, ...result, url: page.url(), commands, note: sandbox._trustedNote,
      proof: sandbox._clickProof, how: sandbox._lastClickHow };
  } finally { await browser.close(); }
}

test('continuously moving target times out without trusted or synthetic click', { timeout: 30000 }, async () => {
  const result = await scenario('unstable');
  assert.equal(result.accepted, false, JSON.stringify(result));
  assert.equal(result.clicks, 0);
  assert.equal(result.page, 1);
  assert.equal(result.events.filter(event => event.type === 'click').length, 0);
  assert.equal(result.commands.filter(command => command.type === 'mousePressed').length, 0);
  assert.match(result.note, /guard-(unstable|timeout)/);
});

test('covered target is not pressed and does not use synthetic fallback', { timeout: 30000 }, async () => {
  const result = await scenario('covered');
  assert.equal(result.accepted, false, JSON.stringify(result));
  assert.equal(result.clicks, 0);
  assert.equal(result.page, 1);
  assert.equal(result.events.filter(event => event.type === 'click').length, 0);
  assert.equal(result.commands.filter(command => command.type === 'mousePressed').length, 0);
  assert.equal(result.note, 'guard-covered');
});

test('replacement during press records uncertain delivery without a second click', { timeout: 30000 }, async () => {
  const result = await scenario('replace-on-press');
  assert.equal(result.accepted, true, 'a dispatched input remains pending for page verification');
  assert.equal(result.changes, 1);
  assert.equal(result.clicks, 0, 'replacement must not receive a duplicate/fallback click');
  assert.equal(result.page, 1);
  assert.equal(result.commands.filter(command => command.type === 'mousePressed').length, 1);
  assert.equal(result.commands.filter(command => command.type === 'mouseReleased').length, 1);
  assert.equal(result.proof.state, 'pending');
  assert.equal(result.proof.gone, true);
  assert.equal(result.proof.ev & 16, 0, 'click receipt on the originally validated element is absent');
  assert.equal(result.proof.ev & 2, 2, 'the originally validated element did receive mousedown');
});

test('missing animation frames still reach a bounded safe stop', { timeout: 30000 }, async () => {
  const result = await scenario('no-frames');
  assert.equal(result.accepted, false, JSON.stringify(result));
  assert.equal(result.clicks, 0);
  assert.equal(result.page, 1);
  assert.equal(result.commands.length, 0);
  assert.match(result.note, /guard-(unstable|timeout)/);
});

test('Chrome scripting rejection before input never falls back to synthetic click', { timeout: 30000 }, async () => {
  const result = await scenario('script-error');
  assert.equal(result.accepted, false, JSON.stringify(result));
  assert.equal(result.clicks, 0);
  assert.equal(result.page, 1);
  assert.equal(result.commands.length, 0);
  assert.equal(result.note, 'guard-error');
});

test('lost Chrome script reply reaches worker deadline and removes the installed observer', { timeout: 30000 }, async () => {
  const result = await scenario('script-reply-lost');
  assert.equal(result.accepted, false, JSON.stringify(result));
  assert.equal(result.clicks, 0);
  assert.equal(result.page, 1);
  assert.equal(result.commands.length, 0);
  assert.equal(result.note, 'guard-timeout');
});

test('error after delivered press cannot trigger a second or synthetic click', { timeout: 30000 }, async () => {
  const result = await scenario('press-error');
  assert.equal(result.accepted, true, JSON.stringify(result));
  assert(result.clicks <= 1, 'uncertain delivery must never duplicate input');
  assert.equal(result.commands.filter(command => command.type === 'mousePressed').length, 1);
  assert.equal(result.commands.filter(command => command.type === 'mouseReleased').length, 1,
    'an uncertain press must finish its single input pair instead of leaving the button held');
  assert.equal(result.proof.ev & 2, 2, 'input reached the page before the API returned an error');
});

test('error after delivered release preserves one received click without retry', { timeout: 30000 }, async () => {
  const result = await scenario('release-error');
  assert.equal(result.accepted, true, JSON.stringify(result));
  assert.equal(result.clicks, 1);
  assert.equal(result.page, 2);
  assert.equal(result.commands.filter(command => command.type === 'mousePressed').length, 1);
  assert.equal(result.commands.filter(command => command.type === 'mouseReleased').length, 1);
  assert.equal(result.proof.state, 'received');
  assert.equal(result.proof.ev & 16, 16, 'receipt survives an API error after the click');
});

test('confirmed debugger attachment failure permits one original synthetic fallback', { timeout: 30000 }, async () => {
  const result = await scenario('attach-error');
  assert.equal(result.accepted, true, JSON.stringify(result));
  assert.equal(result.clicks, 1);
  assert.equal(result.page, 2);
  assert.equal(result.commands.length, 0);
  assert.equal(result.how, 'synth');
  assert.equal(result.note, 'attach-failed');
  assert.equal(result.events.filter(event => event.type === 'click').length, 1);
  assert.equal(result.events.find(event => event.type === 'click').trusted, false);
});

for (const kind of ['baseline', 'smooth', 'layout-on-move']) {
  test('actual scrolling clicks page 2 exactly once: ' + kind, { timeout: 30000 }, async () => {
    const result = await scenario(kind);
    assert.equal(result.accepted, true, JSON.stringify(result));
    assert.equal(result.clicks, 1, JSON.stringify(result));
    assert.equal(result.page, 2);
    assert.equal(new URL(result.url).searchParams.get('pagingIndex'), '2');
    assert.equal(result.how, 'trusted');
    const clickEvents = result.events.filter(event => event.type === 'click');
    assert.equal(clickEvents.length, 1);
    assert.equal(clickEvents[0].target, 'pager');
    assert.equal(clickEvents[0].trusted, true);
    assert.equal(result.commands.filter(command => command.type === 'mousePressed').length, 1);
    assert.equal(result.commands.filter(command => command.type === 'mouseReleased').length, 1);
    if (kind === 'layout-on-move') assert.equal(result.changes, 1, 'fixture must shift after the first pointer move');
  });
}
