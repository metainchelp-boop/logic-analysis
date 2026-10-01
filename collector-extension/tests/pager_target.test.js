// Offline wrong-target regression; actual production functions and fake DOM, no external dependencies.
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
function fixture({ scope = false, marked = false, href = '#', explicitAfter = false, covered = false } = {}) {
  const clicked = [];
  const element = (id, attrs, x) => ({
    id, tagName: 'A', className: id, textContent: '2', disabled: false,
    getAttribute: key => attrs[key] ?? null,
    getBoundingClientRect: () => ({ left: x, top: 100, width: 40, height: 30 }),
    scrollIntoView() {}, contains: () => false, click: () => clicked.push(id),
  });
  const filter = element('filter-count', { href }, 10);
  const real = element('real-pager', marked ? { href: '#', 'data-shp-area': 'prd_pgn.pgn', 'data-shp-contents-id': '2' }
    : { href: '?query=fixture&pagingIndex=2&where=all&vertical=search' }, 100);
  const elements = marked || explicitAfter ? [filter, real] : [filter];
  const document = {
    querySelectorAll: selector => selector.startsWith('[data-shp-area=') ? (marked ? [real] : [])
      : selector.includes('pagination') ? (scope ? [{ querySelectorAll: () => elements }] : [])
      : selector === 'a' ? elements : [],
    elementFromPoint: x => covered ? { tagName: 'DIV', className: 'overlay', textContent: '' } : x < 80 ? filter : real,
  };
  const context = vm.createContext({ URL, document, window: { innerWidth: 1000, innerHeight: 700 },
    location: new URL('https://search.shopping.naver.com/search/all?query=fixture') });
  vm.runInContext(grab('pagerLocate') + '\n' + grab('pagerClick'), context);
  return { context, clicked };
}
test('a standalone numeric href=# filter must not be a page target', () => {
  const f = fixture();
  const target = f.context.pagerLocate(2);
  const branch = f.context.pagerClick(2);
  console.log('OBS standalone', JSON.stringify({ target, branch, clicked: f.clicked }));
  assert.equal(target, null);
  assert.deepEqual(f.clicked, []);
});
test('generic navigation numeric filter must not be a page target', () => {
  const f = fixture({ scope: true });
  const target = f.context.pagerLocate(2);
  const branch = f.context.pagerClick(2);
  console.log('OBS generic-navigation', JSON.stringify({ target, branch, clicked: f.clicked }));
  assert.equal(target, null);
  assert.deepEqual(f.clicked, []);
});
test('both paths select the marked pager even when a generic navigation filter comes first', () => {
  const f = fixture({ scope: true, marked: true });
  assert.equal(f.context.pagerLocate(2).branch, 'shp');
  const branch = f.context.pagerClick(2);
  console.log('OBS differing-paths', JSON.stringify({ branch, clicked: f.clicked }));
  assert.deepEqual(f.clicked, ['real-pager']);
});
test('control: an explicit pagingIndex=1 filter is not page 2', () => {
  const f = fixture({ scope: true, href: '?query=fixture&pagingIndex=1&spec=M10014366' });
  assert.equal(f.context.pagerLocate(2), null);
  assert.equal(f.context.pagerClick(2), '');
  assert.deepEqual(f.clicked, []);
});
test('invalid first candidates do not hide a valid explicit same-query page link', () => {
  for (const href of ['#', '?query=fixture&pagingIndex=1&spec=M10014366', '?query=other&pagingIndex=2',
    '?query=fixture&pagingIndex=2&spec=M10014366', '?query=fixture&pagingIndex=2&query=fixture',
    'https://other.example/search/all?query=fixture&pagingIndex=2', '?query=fixture&pagingIndex=2&vertical=other']) {
    const f = fixture({ scope: true, href, explicitAfter: true });
    assert.equal(f.context.pagerLocate(2).x, 120, href);
    assert.equal(f.context.pagerClick(2), 'num', href);
    assert.deepEqual(f.clicked, ['real-pager'], href);
  }
});
test('a covered genuine candidate stays blocked on both paths', () => {
  const f = fixture({ scope: true, marked: true, covered: true });
  assert.equal(f.context.pagerLocate(2).covered, 1);
  assert.equal(f.context.pagerClick(2), '');
  assert.deepEqual(f.clicked, []);
});
