/**
 * 메타아이앤씨 순위 수집기 v1.12.0 — 안전 중지 서비스 워커.
 *
 * 이 버전은 웹 페이지를 열거나 읽거나 변경하지 않는다. 서비스 워커의 역할은
 * 과거 자동 수집 상태를 제거하고, 이전 팝업 등에서 들어올 수 있는 수동 실행 요청을
 * 명시적으로 거절하는 것뿐이다.
 */

const AUTOMATION_DISABLED = 'AUTOMATION_DISABLED';

// 토큰·worker 식별값·제한된 오류 코드 외에는 이전 자동 수집 실행 상태다.
const STORAGE_KEYS_TO_KEEP = Object.freeze([
  'token',
  'workerId',
  'workerNo',
  'workerCount',
  'lastErrorCode',
]);
const SAFE_ERROR_CODES = new Set([
  'TOKEN_MISSING',
  'STATUS_TIMEOUT',
  'STATUS_AUTH_ERROR',
  'STATUS_HTTP_ERROR',
  'STATUS_INVALID_RESPONSE',
  'STATUS_UNREACHABLE',
]);

/**
 * 기존 버전이 남긴 raw 본문, 탭, 알람, 실행 상태를 whitelist 방식으로 제거한다.
 * 알 수 없는 키도 보존하지 않아 오래된 실행 상태가 이후 버전에 되살아나지 않는다.
 */
async function migrateStorage() {
  const stored = await chrome.storage.local.get(null);
  const allowed = new Set(STORAGE_KEYS_TO_KEEP);
  const keysToRemove = Object.keys(stored).filter((key) =>
    !allowed.has(key) || (key === 'lastErrorCode' && !SAFE_ERROR_CODES.has(stored[key])));
  if (keysToRemove.length) await chrome.storage.local.remove(keysToRemove);
  return { removed: keysToRemove.length };
}

// 설치·업데이트뿐 아니라 unpacked extension reload에서도 migration을 보장한다.
chrome.runtime.onInstalled.addListener(() => migrateStorage().catch(() => undefined));
migrateStorage().catch(() => undefined);

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.cmd === 'run') {
    sendResponse({ ok: false, error: AUTOMATION_DISABLED });
    return false;
  }
  return false;
});
