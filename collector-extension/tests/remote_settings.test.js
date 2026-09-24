/* ⚙ 서버 설정 받기 — 회귀 시험 (v1.27.0 · 대표 확정 2026-09-23 「서버 배포만으로」)
 *
 * 무엇을 막는 시험인가:
 *   ① 서버가 무슨 값을 보내도 안전선을 넘지 못한다(캡차 쉼 1시간 밑 · 간격 20초 밑 · 깊이 10장 위 불가).
 *   ② 서버 값을 못 받거나 이상하면 기본값(= v1.26.0)으로 돈다 — 예외를 밖으로 내지 않는다.
 *   ③ 받은 값이 실제 수집 칸(CFG·RT)에 들어가고, 저장돼 워커가 깨어나도 유지된다.
 *   ④ 한 번짜리 명령은 한 번만 — 만료·모르는 종류·이미 한 것은 안 한다. 캡차 쉼을 푸는 길은 없다.
 *   ⑤ 서버가 이 기계를 멈추면 시간대·밀린 요청 수집 모두 들어가지 않는다.
 *   ⑥ 살아있음 신호가 적용 번호·지문을 보내고, 응답에 실린 설정을 받는다.
 * ⚠️ 소스 문구만 찾으면 주석에 걸리므로 실제 함수를 떼어 가짜 의존으로 돌린다(다른 시험과 같은 방식).
 */
const fs = require('fs');
const path = require('path');
const RS = require('../remote_settings.js');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
const POPUP = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'manifest.json'), 'utf8'));
let pass = 0, fail = 0;
const ok = (name, cond) => { (cond ? pass++ : fail++); console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}`); };

function extract(name, isAsync = true) {
  const head = `${isAsync ? 'async ' : ''}function ${name}(`;
  const i = SRC.indexOf(head);
  if (i < 0) throw new Error(`${name} 을 못 찾았다`);
  let j = SRC.indexOf('{', SRC.indexOf(')', i)), depth = 0, k = j;
  for (; k < SRC.length; k++) {
    if (SRC[k] === '{') depth++;
    else if (SRC[k] === '}') { depth--; if (depth === 0) { k++; break; } }
  }
  return SRC.slice(i, k);
}

/** 가짜 chrome 저장소 + 알람. */
function fakeChrome(init = {}) {
  const store = Object.assign({}, init);
  const alarms = { heartbeat: { name: 'heartbeat', periodInMinutes: 5 } };
  const created = [];
  return {
    store, alarms, created,
    chrome: {
      storage: { local: {
        get: async (k) => { const keys = Array.isArray(k) ? k : [k]; const o = {}; keys.forEach((x) => { if (store[x] !== undefined) o[x] = store[x]; }); return o; },
        set: async (o) => { Object.assign(store, JSON.parse(JSON.stringify(o))); },
        remove: async (k) => { (Array.isArray(k) ? k : [k]).forEach((x) => delete store[x]); },
      } },
      alarms: {
        get: async (n) => alarms[n],
        create: (n, o) => { created.push({ n, o }); alarms[n] = { name: n, periodInMinutes: o.periodInMinutes }; },
      },
    },
  };
}

/** receiveSettings·applyRuntime·loadRemote·runCommands·effectiveWorker 를 한 덩어리로 실제 실행. */
function harness(init = {}) {
  const fc = fakeChrome(init);
  const logs = [];
  const calls = { run: [], flush: 0, arm: 0, upload: [] };
  const CFG = { serverBase: 'http://t', workerNo: 1, workerCount: 1, pagesPerKeyword: 8, maxPages: 8, maxRank: 300,
                readTries: 12, readTriesPaged: 36, readGapMs: 800, minGapMs: 1200, maxGapMs: 3000,
                onDemandGapMs: 20000, onDemandHourCap: 12, hourBudgetMs: 3000000, maxConsecutiveFail: 5 };
  const code = [
    'let RT = RS.merge({}).values;',
    "const RT_KEY = 'remoteSettings'; const ASSIGN_KEY = 'serverAssign'; const CMD_DONE_KEY = 'commandsDone';",
    "let _rtLoaded = false; const HEARTBEAT_ALARM = 'heartbeat';",
    extract('applyRuntime', false), extract('loadRemote'), extract('receiveSettings'),
    extract('effectiveWorker'), extract('serverPaused', false), extract('runCommands'),
    'return { applyRuntime, loadRemote, receiveSettings, effectiveWorker, serverPaused, runCommands, rt: () => RT };',
  ].join('\n');
  const deps = {
    RS, CFG, chrome: fc.chrome,
    log: async (m) => { logs.push(String(m)); },
    armAlarms: () => { calls.arm++; },
    flushOutbox: async () => { calls.flush++; return { sent: 1, left: 0 }; },
    getToken: async () => 'tok',
    uploadReport: async (kind, text) => { calls.upload.push({ kind, len: String(text).length }); return true; },
    runCollection: (manual) => { calls.run.push(manual); },
    globalThis: { CollectorDiagnosticExport: { collect: async () => ({ schemaVersion: 1 }) } },
  };
  const api = new Function(...Object.keys(deps), code)(...Object.values(deps));
  return { api, fc, logs, calls, CFG };
}

const future = () => new Date(Date.now() + 3600e3).toISOString();
const past = () => new Date(Date.now() - 3600e3).toISOString();

(async () => {
  console.log('① 안전선 — 서버가 무슨 값을 보내도');
  let m = RS.merge({ blockCooldownMs: 60000, spreadMinMs: 1000, pagesPerKeyword: 99, slowFactor: 0 });
  ok('🔴 캡차 쉼은 1시간 밑으로 못 줄인다', m.values.blockCooldownMs === 3600000);
  ok('🔴 키워드 간격은 20초 밑으로 못 줄인다', m.values.spreadMinMs === 20000);
  ok('🔴 깊이는 10장 위로 못 늘린다', m.values.pagesPerKeyword === 10);
  ok('당긴 칸을 알려 준다', ['blockCooldownMs', 'spreadMinMs', 'pagesPerKeyword', 'slowFactor'].every((k) => m.clamped.includes(k)));
  m = RS.merge({ readTries: '12', machinePaused: 'yes', nope: 1, swSearchEntry: 0 });
  ok('형식이 틀린 칸은 버리고 기본값', m.values.readTries === 12 && m.values.machinePaused === false && m.values.swSearchEntry === null);
  ok('모르는 칸·틀린 칸을 알려 준다', ['readTries', 'machinePaused', 'nope', 'swSearchEntry'].every((k) => m.rejected.includes(k)));
  for (const junk of [null, undefined, 'x', 3, [1, 2], { values: 1 }]) {
    let threw = false; try { RS.merge(junk); } catch (e) { threw = true; }
    ok(`쓰레기 입력(${JSON.stringify(junk)})에도 예외 없음 · 기본값`, !threw && JSON.stringify(RS.merge(junk).values) === JSON.stringify(RS.merge({}).values));
  }
  m = RS.merge({ pageGapMinMs: 5000, pageGapMaxMs: 1000 });
  ok('최소가 최대보다 크면 최대를 최소에 맞춘다', m.values.pageGapMaxMs === 5000);
  m = RS.merge({ extraBlockPhrases: ['  새 문구  ', 'a', 3, '새 문구', 'x'.repeat(61)] });
  ok('차단 문구 — 다듬고·짧은 것·긴 것·중복·글자 아닌 것 버림', JSON.stringify(m.values.extraBlockPhrases) === JSON.stringify(['새 문구']));
  ok('차단 문구는 더하기만(코드 문구가 빠지지 않는다)', JSON.stringify(RS.blockPhrases(['가', '나'], ['다', '가'])) === JSON.stringify(['가', '나', '다']));
  ok('기본값이 전부 안전선 안', Object.keys(RS.FENCES).every((k) => RS.DEFAULTS[k] >= RS.FENCES[k][0] && RS.DEFAULTS[k] <= RS.FENCES[k][1]));

  console.log('\n② 명령 거르기');
  const cmds = [
    { id: 'a', kind: 'uploadLogs', until: future() },
    { id: 'b', kind: 'uploadLogs', until: past() },
    { id: 'c', kind: 'clearBlocked', until: future() },
    { id: 'd', kind: 'runNow', until: future() },
    { id: '', kind: 'runNow', until: future() },
  ];
  const got = RS.pendingCommands(cmds, ['d'], Date.now()).map((c) => c.id);
  ok('🔴 만료·모르는 종류·이미 한 것·id 없는 것은 안 한다', JSON.stringify(got) === JSON.stringify(['a']));
  ok('🔴 명령 종류에 캡차 쉼을 푸는 것이 없다', !RS.COMMAND_KINDS.some((k) => /block|rest|clear/i.test(k)));

  console.log('\n③ 받은 값이 실제로 들어간다');
  let h = harness();
  await h.api.receiveSettings({ rev: 2, hash: 'h2', values: { pageGapMinMs: 2000, pageGapMaxMs: 5000, pagesPerKeyword: 4, onDemandHourCap: 6 } }, '신호');
  ok('🔴 CFG 페이지 간격·깊이·요청 건 상한에 들어간다', h.CFG.minGapMs === 2000 && h.CFG.maxGapMs === 5000 && h.CFG.pagesPerKeyword === 4 && h.CFG.maxPages === 4 && h.CFG.onDemandHourCap === 6);
  ok('깊이가 바뀌면 maxRank 도 같이(4장 → 150위)', h.CFG.maxRank === 150);
  ok('RT 에도 들어간다', h.api.rt().pageGapMinMs === 2000);
  ok('저장된다(번호·지문·원문)', h.fc.store.remoteSettings && h.fc.store.remoteSettings.rev === 2 && h.fc.store.remoteSettings.hash === 'h2');
  ok('번호가 바뀌면 로그 한 줄', h.logs.some((l) => /서버 설정 2번 적용/.test(l)));
  const nLogs = h.logs.length;
  await h.api.receiveSettings({ rev: 2, hash: 'h2', values: { pageGapMinMs: 2000, pageGapMaxMs: 5000, pagesPerKeyword: 4, onDemandHourCap: 6 } }, '신호');
  ok('같은 번호가 또 오면 로그를 늘리지 않는다(5분마다 도배 금지)', h.logs.length === nLogs);
  // 워커가 잠들었다 깨어난 상황 — 새 하네스에 같은 저장소
  const h2 = harness({ remoteSettings: h.fc.store.remoteSettings });
  ok('깨어나기 전엔 기본값', h2.CFG.minGapMs === 1200);
  await h2.api.loadRemote();
  ok('🔴 깨어나면 저장된 서버 값을 다시 건다', h2.CFG.minGapMs === 2000 && h2.api.rt().pagesPerKeyword === 4);
  for (const junk of [null, 'x', { rev: 1 }, { values: 'x' }]) {
    let threw = false; const h3 = harness();
    try { await h3.api.receiveSettings(junk, '신호'); } catch (e) { threw = true; }
    ok(`이상한 설정(${JSON.stringify(junk)})에 예외 없음 · 그대로 기본값`, !threw && h3.CFG.minGapMs === 1200);
  }
  h = harness();
  await h.api.receiveSettings({ rev: 3, hash: 'h3', values: { heartbeatMin: 2 } }, '신호');
  ok('신호 주기가 바뀌면 heartbeat 알람만 다시 건다', h.fc.created.length === 1 && h.fc.created[0].n === 'heartbeat' && h.fc.created[0].o.periodInMinutes === 2);

  console.log('\n④ 기계 배정');
  h = harness({ workerNo: 1, workerCount: 1 });
  await h.api.receiveSettings({ rev: 1, hash: 'x', values: {}, assign: { no: 2, count: 2 } }, '신호');
  let w = await h.api.effectiveWorker();
  ok('🔴 서버 배정이 팝업 값보다 우선', w.workerNo === 2 && w.workerCount === 2 && w.assigned === true);
  await h.api.receiveSettings({ rev: 1, hash: 'x', values: {} }, '신호');
  w = await h.api.effectiveWorker();
  ok('서버가 배정을 거두면 팝업 값으로 돌아간다', w.workerNo === 1 && w.workerCount === 1 && w.assigned === false);
  await h.api.receiveSettings({ rev: 1, hash: 'x', values: {}, assign: { no: 3, count: 2 } }, '신호');
  ok('형식이 틀린 배정(번호 > 대수)은 무시', (await h.api.effectiveWorker()).assigned === false);

  console.log('\n⑤ 한 번짜리 명령');
  h = harness();
  const list = [{ id: 'L1', kind: 'uploadLogs', until: future() }, { id: 'R1', kind: 'runNow', until: future() },
                { id: 'F1', kind: 'flushOutbox', until: future() }, { id: 'A1', kind: 'rearmAlarms', until: future() },
                { id: 'D1', kind: 'uploadDiag', until: future() }];
  await h.api.receiveSettings({ rev: 1, hash: 'x', values: {}, commands: list }, '신호');
  ok('다섯 가지가 각각 한 번씩', h.calls.upload.length === 2 && h.calls.run.length === 1 && h.calls.flush === 1 && h.calls.arm === 1);
  ok('🔴 지금 수집은 runCollection(false) — 캡차 쉼을 풀지 않는다', h.calls.run[0] === false);
  ok('실행한 id 를 기억한다', ['L1', 'R1', 'F1', 'A1', 'D1'].every((id) => h.fc.store.commandsDone.includes(id)));
  await h.api.receiveSettings({ rev: 1, hash: 'x', values: {}, commands: list }, '신호');
  ok('🔴 같은 명령이 또 와도 다시 하지 않는다', h.calls.upload.length === 2 && h.calls.run.length === 1);

  console.log('\n⑥ 서버 멈춤·스위치');
  h = harness();
  await h.api.receiveSettings({ rev: 4, hash: 'p', values: { machinePaused: true } }, '신호');
  ok('서버 멈춤이 켜진다', h.api.serverPaused() === true);
  const RC = extract('runCollection');
  ok('🔴 시간대 수집은 서버 멈춤이면 들어가지 않는다', /if \(serverPaused\(\)\) \{[\s\S]{0,200}running = false; return;/.test(RC)
     && RC.indexOf('serverPaused()') < RC.indexOf('/api/collector/keywords'));
  const OD = extract('runOnDemand');
  ok('🔴 밀린 요청 수집도 서버 멈춤이면 안 한다', /if \(serverPaused\(\)\) return;/.test(OD) && OD.indexOf('serverPaused()') < OD.indexOf('/api/collector/requests'));
  const CO = extract('runCoordinated');
  ok('서버 중앙 배정 경로도 서버 멈춤이면 안 한다', /if \(serverPaused\(\)\)/.test(CO) && CO.indexOf('serverPaused()') < CO.indexOf("coordRequest('register'"));
  ok('🔴 일시정지(사람)를 먼저 보고 그다음 서버 멈춤 — 순서가 바뀌지 않았다', RC.indexOf('isLocalPaused()') < RC.indexOf('serverPaused()'));
  // 스위치 함수 실제 실행
  const ce = new Function('RT', 'chrome', 'COORD_KEY', `${extract('coordinatedEnabled')}\nreturn coordinatedEnabled;`);
  const chromeOn = fakeChrome({ coordinatedEnabled: true }).chrome;
  ok('중앙 배정 — 서버가 비워 두면(null) 팝업 설정', await ce({ swCoordinated: null }, chromeOn, 'coordinatedEnabled')() === true);
  ok('중앙 배정 — 서버가 끄면 팝업이 켜져 있어도 끔', await ce({ swCoordinated: false }, chromeOn, 'coordinatedEnabled')() === false);
  const se = new Function('RT', 'chrome', `${extract('searchEntryEnabled')}\nreturn searchEntryEnabled;`);
  ok('검색창 진입 — 서버가 끄면 끔', await se({ swSearchEntry: false }, fakeChrome({}).chrome)() === false);
  ok('검색창 진입 — 서버가 비워 두면 종전 기본(켬)', await se({ swSearchEntry: null }, fakeChrome({}).chrome)() === true);
  ok('조기 종료 스위치가 목표를 비운다', /if \(typeof RT === 'object' && RT && RT\.swEarlyStop === false\) _targets = \{\};/.test(RC));
  ok('부분 수집 스위치 — 끄면 올리지 않고 실패로 센다(막힘이면 막힘 처리 그대로)',
     /_isPartial && typeof RT === 'object' && RT && RT\.swUploadPartial === false\) \{\s*if \(payload\.blocked\) throw new Error\(payload\.blocked\);/.test(RC)
     && RC.indexOf('RT.swUploadPartial === false') < RC.indexOf('await uploadKeyword(token, kw, payload)'));
  const TR = extract('tapReport');
  ok('진단 보고 스위치 — 끄면 안 보내되 사람이 누른 것(HUMAN)은 보낸다', /if \(why !== 'HUMAN' && typeof RT === 'object' && RT && RT\.swTapProbe === false\) return;/.test(TR));

  console.log('\n⑦ 살아있음 신호 — 적용 번호를 보내고 응답의 설정을 받는다');
  const HB = extract('sendHeartbeat');
  ok('적용 번호·지문·당긴 칸·실행한 명령·서버 멈춤을 싣는다',
     ['settingsRev:', 'settingsHash:', 'settingsNote:', 'commandsDone:', 'pausedByServer: serverPaused()'].every((s) => HB.includes(s)));
  ok('🔴 응답의 settings 를 receiveSettings 로 넘긴다(성공일 때만)', /if \(res\.ok\) \{[\s\S]{0,160}receiveSettings\(j\.settings, '신호'\)/.test(HB));
  ok('작업 목록 응답의 settings 도 받는다', /if \(settings\) await receiveSettings\(settings, '작업 목록'\);/.test(RC));
  ok('기계 번호는 서버 배정 우선(effectiveWorker)', /await effectiveWorker\(\)/.test(HB) && /await effectiveWorker\(\)/.test(extract('workerParams')) && /await effectiveWorker\(\)/.test(extract('coordWho')));

  console.log('\n⑧ 배선 — 파일·버전·팝업');
  ok('importScripts 에 remote_settings.js · diagnostic_export.js', /importScripts\('rank_rules\.js', 'remote_settings\.js', 'diagnostic_export\.js'\);/.test(SRC));
  ok('manifest 1.27.0 이상', (() => { const [a, b] = MANIFEST.version.split('.').map(Number); return a > 1 || (a === 1 && b >= 27); })());
  ok('알람이 깨울 때 저장된 설정부터 건다', /chrome\.alarms\.onAlarm\.addListener\(async \(a\) => \{\s*await loadRemote\(\);/.test(SRC));
  ok('팝업에 「⚙ 서버 설정 n번 적용됨」 · 서버 배정 줄', /⚙ 서버 설정 <span class="b ok">/.test(POPUP) && /🧮 서버 배정/.test(POPUP));
  ok('🔴 팝업에 그리는 메모는 칸 이름만(글자 걸러서) — 서버 문자열을 그대로 그리지 않는다',
     /replace\(\/\[\^A-Za-z0-9_\]\/g, ''\)/.test(extract('receiveSettings')));
  ok('🔴 pageExtract — 서버 문구는 코드 문구 판정 **뒤에** 더한다(코드 문구가 먼저)',
     (() => { const pe = extract('pageExtract', false); return pe.indexOf('보안 확인을 완료') < pe.indexOf('extraBlock[bi]') && /if \(!blocked && Array\.isArray\(extraBlock\)\)/.test(pe); })());

  console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : `\n서버 설정 시험 전부 통과 (${pass}건)`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('시험 자체가 죽음:', e); process.exit(1); });
