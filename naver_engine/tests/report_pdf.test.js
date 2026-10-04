'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const assets = path.resolve(__dirname, '../../backend/naver_page/vendor/report-pdf');
const report = () => ({report_id: 17, revision_no: 3, generated_at: '2026-10-04T10:00:00+09:00',
  company_name: '한글 성과검증 업체', owner: '담당자', status: 'partial',
  scope: {kind: 'account', ad_account_no: '1234567', account_name: '광고계정', accounts: []},
  payload: {format_version: 2, period: {kind: 'weekly', start: '2026-09-21', end: '2026-09-27'},
    status: 'partial', totals: {spend: 123456.75, impressions: 54321, clicks: 123, conversions: null, conversion_value: null},
    ratios: {ctr: 0.226431766, cpc: 1003.71341463, roas: null},
    coverage: {accounts: 1, expected_account_days: 7, basic_complete_account_days: 6,
      conversion_complete_account_days: 0, basic_complete: false, conversion_complete: false},
    details: {status: 'available', daily: [], comparison: {status: 'insufficient_data'},
      briefing: ['기본 성과는 7일 중 6일 집계되었습니다.'], management_records: [], next_actions: []}}});

test.before(() => {
  global.PDFLib = require(path.join(assets, 'pdf-lib-1.17.1.min.js'));
  global.fontkit = require(path.join(assets, 'fontkit-1.1.1.umd.min.js'));
  global.sha256 = require(path.join(assets, 'sha256-1.0.0.min.js')).sha256;
  global.fetch = async url => {
    assert.equal(url, '/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz');
    const bytes = fs.readFileSync(path.join(assets, 'NanumGothic-Regular.ttf.gz'));
    return {ok: true, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)};
  };
});

test('approved report builds genuine A4 PDF bytes without altering the pinned report', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js');
  const input = report(), original = JSON.stringify(input);
  const bytes = await pdf.build(input);
  assert.ok(bytes instanceof Uint8Array);
  assert.equal(Buffer.from(bytes.subarray(0, 5)).toString(), '%PDF-');
  const parsed = await global.PDFLib.PDFDocument.load(bytes);
  assert.equal(parsed.getTitle(), '한글 성과검증 업체 주간 광고 성과 보고서');
  for (const page of parsed.getPages()) {
    assert.ok(Math.abs(page.getWidth() - 595.28) < 0.1);
    assert.ok(Math.abs(page.getHeight() - 841.89) < 0.1);
  }
  assert.equal(JSON.stringify(input), original);
});

module.exports = {report};

async function extracted(bytes) {
  const doc = await global.PDFLib.PDFDocument.load(bytes), map = new Map(), streams = [];
  for (const [, value] of doc.context.enumerateIndirectObjects()) {
    if (!(value instanceof global.PDFLib.PDFRawStream)) continue;
    const content = Buffer.from(global.PDFLib.decodePDFRawStream(value).decode()).toString();
    if (content.includes('beginbfchar')) {
      for (const match of content.matchAll(/<([\da-f]{4})>\s*<([\da-f]+)>/gi)) {
        map.set(match[1].toUpperCase(), match[2].match(/.{4}/g).map(h => String.fromCharCode(parseInt(h, 16))).join(''));
      }
    } else if (content.includes('BT')) streams.push(content);
  }
  return streams.map(stream => Array.from(stream.matchAll(/<([\da-f]+)>\s*Tj/gi), match =>
    match[1].match(/.{4}/g).map(key => map.get(key.toUpperCase()) || '').join('')).join('\n')).join('\n');
}

test('PDF preserves pinned numbers, partial notices, Korean wrapping and revision without internal fields', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js'), input = report();
  input.company_name = '한글 업체명이 매우 길어도 줄바꿈으로 보존하는 검증 '.repeat(6);
  input.owner = {name: '담당자', team_name: '비공개 조직', emp_id: 'PRIVATE_EMPLOYEE'};
  input.payload.internal_memo = 'PRIVATE_MEMO'; input.payload.bizmoney = 999999;
  input.payload.details.management_records = [{note: 'PRIVATE_RECORD'}];
  input.payload.details.next_actions = ['PRIVATE_NEXT'];
  input.payload.details.daily = Array.from({length: 7}, (_, i) => ({day: '2026-09-' + (21 + i),
    status: i === 2 ? 'collecting' : 'partial', totals: {spend: i === 2 ? null : 1234.75,
      impressions: i === 2 ? null : 4321, clicks: i === 2 ? null : 23}, coverage: {basic_complete: i !== 2}}));
  const bytes = await pdf.build(input), content = await extracted(bytes);
  for (const expected of ['부분 집계', '123,456원', '54,321회', '123회', '전환 미확인',
    '3판', '2026-09-21', '2026-09-27', '기본 성과 6 / 7', '전환 성과 0 / 7', '2026-09-23', '미확인', '직전 기간 비교']) {
    assert.ok(content.includes(expected), expected + '\n' + content);
  }
  for (const privateText of ['PRIVATE', '999,999', '비공개 조직', 'bizmoney', 'API', '진단']) assert.ok(!content.includes(privateText));
  const doc = await global.PDFLib.PDFDocument.load(bytes);
  assert.ok(doc.getPageCount() >= 2);
  for (let i = 1; i <= doc.getPageCount(); i++) assert.ok(content.includes(i + ' / ' + doc.getPageCount()));
  if (process.env.NAVER_PDF_QA_OUTPUT) fs.writeFileSync(process.env.NAVER_PDF_QA_OUTPUT, bytes);
});

test('direct download fails closed for missing or changed authority and uses a safe PDF filename', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js');
  await assert.rejects(() => pdf.download(report()), /REPORT_PDF_STALE/);
  let checks = 0, clicks = 0, revoked = 0, link;
  global.document = {createElement: tag => {
    assert.equal(tag, 'a');
    link = {click: () => clicks++, remove() {}}; return link;
  }, body: {appendChild() {}}};
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = blob => { assert.equal(blob.type, 'application/pdf'); return 'blob:local-test'; };
  URL.revokeObjectURL = () => revoked++;
  try {
    await assert.rejects(() => pdf.download(report(), {isCurrent: () => ++checks === 1}), /REPORT_PDF_STALE/);
    assert.equal(clicks, 0);
    const input = report(); input.company_name = '../한글\\업체\u0000:*?<>|';
    const result = await pdf.download(input, {isCurrent: () => true});
    assert.equal(clicks, 1);
    assert.ok(result.filename.endsWith('_1234567_주간_2026-09-21_2026-09-27_v3.pdf'));
    assert.ok(!/[\\/:*?<>|\u0000-\u001f]/.test(result.filename));
    assert.equal(link.download, result.filename);
    assert.equal(result.bytes > 1000, true);
    assert.equal(revoked, 0); // Keep the object URL alive long enough for browser download consumption.
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; delete global.document; }
});

test('company scope, percentage-point comparison and legacy gaps are explicit, never invented', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js'), input = report();
  input.scope = {kind: 'company', accounts: [{ad_account_no: '123', account_name: '검색 광고'}, {ad_account_no: '456', account_name: '브랜드 광고'}]};
  input.payload.details.comparison = {period: {start: '2026-09-14', end: '2026-09-20'}, status: 'partial', basic_status: 'ready',
    conversion_status: 'scope_changed', totals: {spend: 0, impressions: 12345}, ratios: {ctr: 1},
    changes: {ctr: {absolute: -0.77, percent: null, unit: 'percentage_points', status: 'ready'},
      spend: {absolute: 123456.75, percent: null, unit: 'currency', status: 'zero_denominator'},
      conversions: {absolute: null, percent: null, unit: 'count', status: 'scope_changed'}}};
  let content = await extracted(await pdf.build(input));
  for (const expected of ['업체 전체 합산', '포함 계정 2개', '검색 광고', '브랜드 광고', '-0.77%p', '증감률 산출 불가', '비교 범위 변경', '2026-09-14']) assert.ok(content.includes(expected), expected);
  input.payload.format_version = 1; input.payload.details = {status: 'legacy_unavailable'};
  content = await extracted(await pdf.build(input));
  assert.ok(content.includes('옛 판 상세 미보관'));
  assert.ok(content.includes('해당 판의 일별 상세 미보관'));
  assert.ok(!content.includes('-0.77%p'));
});

test('font corruption cannot produce a download and report data remains pinned across asynchronous loading', async () => {
  const modulePath = require.resolve('../../backend/naver_page/report-pdf.js');
  delete require.cache[modulePath];
  const pdf = require(modulePath), oldFetch = global.fetch;
  let release;
  global.fetch = async () => ({ok: true, arrayBuffer: async () => new Uint8Array(20).buffer});
  await assert.rejects(() => pdf.build(report()), /REPORT_PDF_FONT/);
  global.fetch = () => new Promise(resolve => { release = () => resolve(oldFetch('/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz')); });
  const input = report(), pending = pdf.build(input);
  await new Promise(resolve => setImmediate(resolve));
  input.company_name = 'CHANGED AFTER CLICK'; input.payload.totals.spend = 999999;
  release(); const content = await extracted(await pending);
  assert.ok(content.includes('한글 성과검증 업체'));
  assert.ok(!content.includes('CHANGED AFTER CLICK'));
  assert.ok(content.includes('123,456원'));
  global.fetch = oldFetch;
});

test('invalid numbers, oversized text, day drift and unsupported ranges fail closed', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js');
  for (const mutate of [r => r.payload.totals.spend = '123', r => r.payload.totals.spend = NaN,
    r => r.payload.totals.spend = -1, r => r.company_name = '가'.repeat(241),
    r => r.scope.kind = 'unknown', r => r.payload.period.start = '2026-02-31',
    r => r.payload.details.daily = [{day: '2026-09-20', totals: {}}]]) {
    const input = report(); mutate(input); await assert.rejects(() => pdf.build(input), /REPORT_PDF_DATA/);
  }
});

test('embedded Korean composite glyphs retain outlines, not merely searchable character mappings', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js');
  const doc = await global.PDFLib.PDFDocument.load(await pdf.build(report()));
  let embedded, cmap;
  for (const [, value] of doc.context.enumerateIndirectObjects()) {
    if (!(value instanceof global.PDFLib.PDFRawStream)) continue;
    const raw = global.PDFLib.decodePDFRawStream(value).decode();
    if (['00010000', '74727565'].includes(Buffer.from(raw.subarray(0, 4)).toString('hex'))) embedded = global.fontkit.create(raw);
    if (Buffer.from(raw).toString().includes('beginbfchar')) cmap = Buffer.from(raw).toString();
  }
  assert.ok(embedded && cmap);
  for (const match of cmap.matchAll(/<([\da-f]{4})>\s*<([\da-f]{4})>/gi)) {
    const cp = parseInt(match[2], 16);
    if (cp >= 0xac00 && cp <= 0xd7a3) {
      assert.ok(embedded.getGlyph(parseInt(match[1], 16)).path.commands.length > 0, String.fromCharCode(cp));
    }
  }
});

test('money matches the screen truncation, including decimal CPC without altering the stored value', async () => {
  const input = report(); input.payload.ratios.cpc = 199.6; input.payload.ratios.ctr = 1.005;
  const content = await extracted(await require('../../backend/naver_page/report-pdf.js').build(input));
  assert.ok(content.includes('199원'));
  assert.ok(!content.includes('200원'));
  assert.ok(content.includes('123,456원'));
  assert.equal(input.payload.ratios.cpc, 199.6);
  assert.ok(content.includes('1%'));
  assert.ok(!content.includes('1.01%'));
});

test('partial company-day numbers remain in the table but never draw a complete-day chart marker', async () => {
  const pdf = require('../../backend/naver_page/report-pdf.js'), input = report();
  input.payload.details.daily = [
    {day: '2026-09-21', totals: {spend: 50, impressions: 100, clicks: 5}, coverage: {basic_complete: true}},
    {day: '2026-09-22', totals: {spend: 999, impressions: 999, clicks: 999}, coverage: {basic_complete: false}},
    {day: '2026-09-23', totals: {spend: 75, impressions: 150, clicks: 7}, coverage: {basic_complete: true}}
  ];
  async function graphics(bytes) {
    const doc = await global.PDFLib.PDFDocument.load(bytes);
    const streams = [];
    for (const [, value] of doc.context.enumerateIndirectObjects()) {
      if (!(value instanceof global.PDFLib.PDFRawStream)) continue;
      const str = Buffer.from(global.PDFLib.decodePDFRawStream(value).decode()).toString();
      if (str.includes('BT')) streams.push(...str.split('\n').filter(line => / (m|l|c)$/.test(line)));
    }
    return streams;
  }
  const partial = await pdf.build(input);
  assert.ok((await extracted(partial)).includes('999원'));
  input.payload.details.daily[1].totals = {spend: null, impressions: null, clicks: null};
  assert.deepEqual(await graphics(partial), await graphics(await pdf.build(input)));
});

test('HTTP without SubtleCrypto still verifies the fixed compressed and original font digests', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(global, 'crypto'), originalFetch = global.fetch;
  const modulePath = require.resolve('../../backend/naver_page/report-pdf.js');
  try {
    Object.defineProperty(global, 'crypto', {value: undefined, configurable: true});
    assert.equal(global.sha256('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    assert.equal(global.sha256(''), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    delete require.cache[modulePath];
    const bytes = await require(modulePath).build(report());
    assert.ok((await extracted(bytes)).includes('한글 성과검증 업체'));
    global.fetch = async url => {
      const response = await originalFetch(url), bytes = new Uint8Array(await response.arrayBuffer());
      bytes[bytes.length - 12] ^= 1; // Same size, wrong digest: reject before decompression.
      return {ok: true, arrayBuffer: async () => bytes.buffer};
    };
    delete require.cache[modulePath];
    await assert.rejects(() => require(modulePath).build(report()), /REPORT_PDF_FONT/);
  } finally {
    Object.defineProperty(global, 'crypto', descriptor); global.fetch = originalFetch;
    delete require.cache[modulePath];
  }
});
