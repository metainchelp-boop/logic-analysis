'use strict';
// Pure display contract; no browser, network, credentials, or production data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../backend/naver_page/app.js'), 'utf8');
const begin = source.indexOf('  var RUNTIME_LABELS = ');
const end = source.indexOf('  function renderRuntime()', begin);
assert.ok(begin > 0 && end > begin, 'runtime display model must exist');
const context = {plain: v => v && typeof v === 'object' && !Array.isArray(v), isFinite};
vm.runInNewContext(source.slice(begin, end), context);
const value = {state:'collecting', indicator:'green', reason_code:'COLLECTING',
  verified_at:'2026-10-03T21:30:00+09:00', valid_for_seconds:25, retry_at:null};
assert.equal(context.runtimeModel(value, 0).indicator, 'green');
assert.equal(context.runtimeModel(value, 24999).indicator, 'green');
assert.equal(context.runtimeModel(value, 25000).indicator, 'red');
assert.equal(context.runtimeModel({...value,state:'waiting',reason_code:'WAITING'}, 0).indicator, 'green');
assert.equal(context.runtimeModel({...value,state:'rate_paused',indicator:'red',reason_code:'RATE_LIMITED'}, 0).indicator, 'red');
for (const changed of [{state:'stopped'}, {reason_code:'<img src=x>'}, {valid_for_seconds:Infinity},
  {valid_for_seconds:true}, {verified_at:null}, {verified_at:'yesterday'}]) {
  assert.equal(context.runtimeModel({...value,...changed},0).indicator,'red');
}
assert.equal(context.runtimeModel(null, 0).indicator, 'red');
assert.equal(context.runtimeModel({reason_code:'__proto__',valid_for_seconds:20,verified_at:null,retry_at:null}, 0).indicator,'red');
assert.ok(!context.runtimeModel({...value,reason_code:'private'},0).label.includes('private'));
console.log('runtime display model: 14 assertions passed');
