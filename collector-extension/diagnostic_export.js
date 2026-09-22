/* 🧾 진단 파일 — 코덱스 1.22.0 `diagnostic_export.js` 이식판 (3차 · 2026-09-22)
 *
 * 무엇을 하나: 팝업 「🧾 진단 파일 저장」이 이 기계의 **상태·건수만** 허용 목록으로 새로 만들어 JSON 으로 내려준다.
 *   대표가 노트북 앞에서 파일 하나 뽑아 보내면, 로그 사진·말로 설명하던 것을 갈음한다(2번 노트북 같은 상황).
 * 무엇을 안 하나: 저장소 레코드를 그대로 직렬화하지 않는다 — 토큰·검색어(current)·상품·원문·기계 식별자(instanceId)·
 *   자유 문장(사유·오류·로그)은 **절대 싣지 않는다**. 값이 있었는지(PRESENT/NONE)만 적는다.
 *   네이버·서버에 요청을 보내지 않고, 저장소를 고치지도 않는다(읽기만).
 * ⚠️ 허용 목록에 없는 키는 나가지 않는다 — 새 상태 칸을 실으려면 여기 목록에 넣고 node 시험을 고칠 것.
 */
(function () {
  'use strict';
  const STATES = ['READY', 'LEASED', 'IDLE', 'WAIT_BUDGET', 'PAUSED_OPERATOR', 'PAUSED_BLOCK', 'PAUSED_AUTH',
    'SESSION_MISMATCH', 'INACTIVE', 'NO_V2', 'SERVER_UNREACHABLE', 'OFF'];
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const count = (value, max = 1000000) => Number.isSafeInteger(value) && value >= 0 && value <= max ? value : null;
  const member = (value, allowed) => typeof value === 'string' && allowed.includes(value) ? value : (value === undefined || value === '' ? 'NONE' : 'UNKNOWN');
  const flag = value => value === true ? 'ON' : value === false ? 'OFF' : 'UNKNOWN';
  const presence = value => (value === undefined || value === null || value === '') ? 'NONE' : 'PRESENT';
  function timestamp(value) {
    // 저장된 ISO(밀리초·Z) 또는 epoch 밀리초만 받는다 — 자유 문자열은 싣지 않는다.
    const ms = typeof value === 'number' ? value
      : typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value) ? Date.parse(value) : NaN;
    if (!Number.isSafeInteger(ms) || ms < 0 || ms > 4102444800000) return null;
    const result = new Date(ms).toISOString();
    return typeof value === 'string' && result !== value ? null : result;
  }
  function version(value) {
    return typeof value === 'string' && /^(0|[1-9]\d{0,4})(\.(0|[1-9]\d{0,4})){0,3}$/.test(value) ? value : null;
  }
  function future(value, now) {   // 쉼 만료 시각 — 남은 분만(시각 원문은 안 싣는다)
    return typeof value === 'number' && Number.isSafeInteger(value) && value > now ? Math.ceil((value - now) / 60000) : 0;
  }
  /** chrome.storage.local 의 {state, coordinatedEnabled, token, workerNo, workerCount} 에서 허용된 것만. */
  function summarizeLocal(local, now = Date.now()) {
    if (!record(local) || (local.state !== undefined && !record(local.state))) return { availability: 'INVALID_STATE' };
    const state = local.state || {};
    const counts = {};
    for (const key of ['target', 'done', 'partial', 'failed', 'overdue', 'dayTotal', 'dayDone', 'dayFailed']) counts[key] = count(state[key]);
    return {
      availability: 'AVAILABLE',
      tokenSaved: flag(typeof local.token === 'string' ? local.token.length > 0 : undefined),
      worker: { no: count(local.workerNo, 9), count: count(local.workerCount, 9) },
      coordinatedEnabled: flag(local.coordinatedEnabled === true ? true : local.coordinatedEnabled === false || local.coordinatedEnabled === undefined ? false : undefined),
      coordState: member(state.coordState, STATES), coordReason: presence(state.coordReason),
      coordNextAt: timestamp(state.coordNextAt),
      running: flag(state.running === 'daily' || state.running === 'ondemand' ? true : state.running === false ? false : state.running === true ? true : undefined),
      pausedByLocal: flag(state.pausedByLocal), pausedByScreen: flag(state.pausedByScreen),
      blocked: presence(state.blocked), blockedMinutesLeft: future(state.blockedUntil, now),
      slowMinutesLeft: future(state.slowUntil, now),
      currentKeyword: presence(state.current),          // 검색어 원문은 싣지 않는다
      lastError: presence(state.error),                 // 오류 문장은 싣지 않는다
      heartbeat: { at: timestamp(state.lastHeartbeatAt), ok: flag(state.lastHeartbeatOk), note: presence(state.lastHeartbeatNote) },
      startedAt: timestamp(state.startedAt), finishedAt: timestamp(state.finishedAt),
      counts,
    };
  }
  async function readLocal(chromeApi, now) {
    let timer;
    try {
      return await Promise.race([
        Promise.resolve().then(() => chromeApi.storage.local.get(['state', 'coordinatedEnabled', 'token', 'workerNo', 'workerCount']))
          .then(local => summarizeLocal(local, now)),
        new Promise(resolve => { timer = setTimeout(() => resolve({ availability: 'READ_TIMEOUT' }), 3000); }),
      ]);
    } catch (_) { return { availability: 'READ_ERROR' }; }
    finally { clearTimeout(timer); }
  }
  async function readAlarms(chromeApi) {
    try {
      if (!chromeApi.alarms || typeof chromeApi.alarms.getAll !== 'function') return { availability: 'UNSUPPORTED' };
      const all = await new Promise(resolve => { try { const r = chromeApi.alarms.getAll(resolve); if (r && r.then) r.then(resolve); } catch (_) { resolve(null); } });
      if (!Array.isArray(all)) return { availability: 'READ_ERROR' };
      const names = all.map(a => (a && typeof a.name === 'string' && ['daily', 'ondemand', 'heartbeat'].includes(a.name)) ? a.name : 'OTHER');
      return { availability: 'AVAILABLE', count: all.length, names };
    } catch (_) { return { availability: 'READ_ERROR' }; }
  }
  async function collect({ chromeApi = globalThis.chrome, now = Date.now() } = {}) {
    let extensionVersion = null;
    try { extensionVersion = version(chromeApi.runtime.getManifest().version); } catch (_) { /* 모르면 null */ }
    const [local, alarms] = await Promise.all([readLocal(chromeApi, now), readAlarms(chromeApi)]);
    return { schemaVersion: 1, exportedAt: timestamp(now), extensionVersion, snapshot: 'INDEPENDENT_LOCAL_READS', local, alarms };
  }
  const api = { collect, summarizeLocal, timestamp, version };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.CollectorDiagnosticExport = api;
})();
