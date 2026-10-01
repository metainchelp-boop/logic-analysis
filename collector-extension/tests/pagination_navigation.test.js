// Offline regression probes for the unmodified 1.27.0 source.
// No browser, network, credentials, or production mutation.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const src = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
function grab(name) {
  const start = src.search(new RegExp('(?:async )?function ' + name + '\\('));
  if (start < 0) throw new Error('Missing function: ' + name);
  let depth = 0;
  for (let i = src.indexOf('{', start); i < src.length; i++) {
    if (src[i] === '{') depth++;
    if (src[i] === '}' && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error('Unclosed function: ' + name);
}
async function scenario({ transitionMs, covered = 0 }) {
  let now = 0, releasedAt = null, synth = 0;
  const events = [];
  const ctx = {
    Math, String, Promise, setTimeout, clearTimeout,
    _trustedNote: '', _clickHit: '', _clickCovered: 0, _pagerAfter: '',
    _lastClickBranch: '', _lastClickHow: '',
    _navMode: { how: { trusted: 0, synth: 0 } },
    sleep: async ms => { now += ms; },
    dbgAttach: async () => {}, dbgDetach: async () => {},
    humanScrollDown: async () => {}, trustedEnabled: async () => true,
    dbgSend: async (_tab, _method, params) => {
      events.push(params.type);
      if (params.type === 'mouseReleased') releasedAt = now;
    },
    pagerLocate: function pagerLocate() {}, pagerClick: function pagerClick() {},
    pagerState: function pagerState() {},
    chrome: { debugger: {}, scripting: { executeScript: async ({ func, args }) => {
      if (func.name === 'pagerLocate' && args[1]?.phase === 'finish') return [{ result: { ev: 0, gone: false, js: 0 } }];
      if (func.name === 'pagerLocate') return [{ result: { branch: 'num', x: 120, y: 210,
        reason: covered ? 'covered' : 'stable', hit: covered ? 'div.overlay' : 'a.page>2', covered } }];
      if (func.name === 'pagerState') return [{ result: { cur: releasedAt !== null && now - releasedAt >= transitionMs ? '2' : '1' } }];
      if (func.name === 'pagerClick') { synth++; return [{ result: 'num' }]; }
      throw new Error('Unexpected script: ' + func.name);
    } } },
  };
  vm.createContext(ctx);
  vm.runInContext(['pagerGuardCall', 'readPagerState', 'trustedClickToPage', 'clickToPage'].map(grab).join('\n'), ctx);
  const accepted = await ctx.clickToPage(1, 2);
  return { accepted, synth, events, note: ctx._trustedNote, mode: ctx._lastClickHow };
}

test('control: a 100 ms page transition needs only one click', async () => {
  const r = await scenario({ transitionMs: 100 });
  assert.equal(r.accepted, true);
  assert.equal(r.synth, 0);
  assert.equal(r.mode, 'trusted');
});

test('red: a still-pending 800 ms transition must not be clicked again after 200 ms', async () => {
  const r = await scenario({ transitionMs: 800 });
  assert.equal(r.synth, 0, 'Actual: a synthetic click was issued while the first transition was still pending: ' + JSON.stringify(r));
});

test('red: a known-covered target must not receive a coordinate click', async () => {
  const r = await scenario({ transitionMs: 800, covered: 1 });
  assert.equal(r.events.includes('mousePressed'), false, 'Actual: coordinate click dispatched into an acknowledged overlay: ' + JSON.stringify(r));
});
