const SERVER_BASE = 'https://logic.metainc.co.kr';
const STATUS_TIMEOUT_MS = 5000;
const OPERATION_MODES = new Set(['legacy', 'paused', 'v2_record', 'v2_project']);
const CIRCUIT_STATES = new Set(['CLOSED', 'OPEN', 'NOT_READY']);
const SAFE_ERROR_CODES = new Set([
  'TOKEN_MISSING',
  'STATUS_TIMEOUT',
  'STATUS_AUTH_ERROR',
  'STATUS_HTTP_ERROR',
  'STATUS_INVALID_RESPONSE',
  'STATUS_UNREACHABLE',
]);

const ERROR_LABELS = {
  TOKEN_MISSING: '서버 토큰이 없어 상태를 확인하지 못했습니다.',
  STATUS_TIMEOUT: '서버 상태 확인 시간이 초과되었습니다.',
  STATUS_AUTH_ERROR: '서버 인증에 실패했습니다.',
  STATUS_HTTP_ERROR: '서버가 상태 요청을 처리하지 못했습니다.',
  STATUS_INVALID_RESPONSE: '서버 상태 응답의 필수 항목이 없거나 서로 맞지 않습니다.',
  STATUS_UNREACHABLE: '서버 상태를 확인하지 못했습니다.',
};

const $ = (id) => document.getElementById(id);

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = String(value);
}

function setSummaryTone(tone) {
  const element = $('serverSummary');
  if (!element) return;
  element.classList.remove('ok', 'warn', 'bad');
  if (tone) element.classList.add(tone);
}

function boundedServerString(value) {
  return String(value).slice(0, 80);
}

function isValidStatusPayload(payload) {
  if (!payload || typeof payload !== 'object' ||
      typeof payload.operationMode !== 'string' || !OPERATION_MODES.has(payload.operationMode) ||
      typeof payload.effectivePaused !== 'boolean' ||
      typeof payload.circuitState !== 'string' || !CIRCUIT_STATES.has(payload.circuitState) ||
      typeof payload.schemaReady !== 'boolean' ||
      typeof payload.legacyWritesEnabled !== 'boolean') {
    return false;
  }

  const legacyMode = payload.operationMode === 'legacy';
  if (payload.effectivePaused !== !legacyMode ||
      payload.legacyWritesEnabled !== legacyMode) {
    return false;
  }

  if (legacyMode || payload.operationMode === 'paused') {
    return payload.schemaReady === false && payload.circuitState === 'NOT_READY';
  }
  // 스키마와 운영 provision은 별개다. 테이블은 준비됐어도 필수 source 회로 행이
  // 아직 만들어지지 않은 첫 배포 단계는 schemaReady=true/NOT_READY가 정상이다.
  return payload.schemaReady
    ? payload.circuitState === 'CLOSED' || payload.circuitState === 'OPEN' ||
      payload.circuitState === 'NOT_READY'
    : payload.circuitState === 'NOT_READY';
}

function renderUnavailable(errorCode) {
  const code = SAFE_ERROR_CODES.has(errorCode) ? errorCode : 'STATUS_UNREACHABLE';
  setText('serverSummary', '서버 상태 확인 불가');
  setSummaryTone('bad');
  setText('operationMode', '확인 불가');
  setText('effectivePaused', '확인 불가');
  setText('circuitState', '확인 불가');
  setText('schemaReady', '확인 불가');
  setText('legacyWritesEnabled', '확인 불가');
  setText('checkedAt', new Date().toLocaleString('ko-KR'));
  setText('lastError', `${code} · ${ERROR_LABELS[code]}`);
  return code;
}

function renderServerStatus(payload) {
  const stopped = payload.effectivePaused === true && payload.legacyWritesEnabled === false;
  setText('serverSummary', stopped
    ? '기존 자동 수집 경로 중지 확인'
    : '기존 수집 경로 중지 미확인 — 운영 확인 필요');
  setSummaryTone(stopped ? 'ok' : 'warn');
  setText('operationMode', boundedServerString(payload.operationMode));
  setText('effectivePaused', payload.effectivePaused ? '중지됨' : '중지되지 않음');
  setText('circuitState', boundedServerString(payload.circuitState));
  setText('schemaReady', payload.schemaReady ? '준비됨' : '준비되지 않음');
  setText('legacyWritesEnabled', payload.legacyWritesEnabled ? '허용됨' : '차단됨');
  setText('checkedAt', new Date().toLocaleString('ko-KR'));
  setText('lastError', '');
}

async function rememberErrorCode(code) {
  try {
    if (code) await chrome.storage.local.set({ lastErrorCode: code });
    else await chrome.storage.local.remove('lastErrorCode');
  } catch (_error) {
    // 화면 상태가 저장소 오류 때문에 정상으로 보이면 안 되므로 표시 결과는 유지한다.
  }
}

function taggedError(code) {
  const error = new Error(code);
  error.safeCode = code;
  return error;
}

async function requestServerStatus(token) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);
  try {
    const response = await fetch(`${SERVER_BASE}/api/collector/status`, {
      method: 'GET',
      headers: { 'X-Collector-Token': token },
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
      signal: controller.signal,
    });
    if (response.status === 401 || response.status === 403) throw taggedError('STATUS_AUTH_ERROR');
    if (!response.ok) throw taggedError('STATUS_HTTP_ERROR');

    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw taggedError('STATUS_INVALID_RESPONSE');
    }
    if (!isValidStatusPayload(payload)) throw taggedError('STATUS_INVALID_RESPONSE');
    return payload;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function refreshStatus() {
  const button = $('refresh');
  if (button) button.disabled = true;
  setText('serverSummary', '서버 상태 확인 중…');
  setSummaryTone('');
  setText('operationMode', '확인 중…');
  setText('effectivePaused', '확인 중…');
  setText('circuitState', '확인 중…');
  setText('schemaReady', '확인 중…');
  setText('legacyWritesEnabled', '확인 중…');

  try {
    const { token = '' } = await chrome.storage.local.get('token');
    if (!token) {
      const code = renderUnavailable('TOKEN_MISSING');
      await rememberErrorCode(code);
      const setup = $('setup');
      if (setup) setup.open = true;
      return;
    }

    const payload = await requestServerStatus(token);
    renderServerStatus(payload);
    await rememberErrorCode('');
  } catch (error) {
    const code = error && error.name === 'AbortError'
      ? 'STATUS_TIMEOUT'
      : (error && error.safeCode) || 'STATUS_UNREACHABLE';
    const safeCode = renderUnavailable(code);
    await rememberErrorCode(safeCode);
  } finally {
    if (button) button.disabled = false;
  }
}

function boundedInteger(value, fallback, maximum) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(1, parsed));
}

async function loadSettings() {
  const stored = await chrome.storage.local.get([
    'token', 'workerId', 'workerNo', 'workerCount', 'lastErrorCode',
  ]);
  $('token').value = stored.token || '';
  $('workerId').value = stored.workerId || '';
  $('workerNo').value = boundedInteger(stored.workerNo, 1, 99);
  $('workerCount').value = boundedInteger(stored.workerCount, 1, 99);

  if (!stored.token) $('setup').open = true;
  if (SAFE_ERROR_CODES.has(stored.lastErrorCode)) {
    setText('lastError', `${stored.lastErrorCode} · ${ERROR_LABELS[stored.lastErrorCode]}`);
  }
}

async function saveSettings() {
  const workerCount = boundedInteger($('workerCount').value, 1, 99);
  const workerNo = Math.min(workerCount, boundedInteger($('workerNo').value, 1, 99));
  await chrome.storage.local.set({
    token: $('token').value.trim(),
    workerId: $('workerId').value.trim().slice(0, 80),
    workerNo,
    workerCount,
  });
  $('workerNo').value = workerNo;
  $('workerCount').value = workerCount;
  setText('saveResult', '저장했습니다.');
  await refreshStatus();
}

async function initialize() {
  $('refresh').addEventListener('click', refreshStatus);
  $('save').addEventListener('click', () => {
    saveSettings().catch(async () => {
      const code = renderUnavailable('STATUS_UNREACHABLE');
      await rememberErrorCode(code);
    });
  });

  try {
    await loadSettings();
  } catch (_error) {
    const code = renderUnavailable('STATUS_UNREACHABLE');
    await rememberErrorCode(code);
    return;
  }
  await refreshStatus();
}

if (typeof document !== 'undefined') initialize();
