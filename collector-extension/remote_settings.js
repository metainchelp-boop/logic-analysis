/* 서버가 주는 설정값을 안전하게 받아 쓰는 규칙(순수 함수) — v1.27.0 (대표 확정 2026-09-23)
 *
 * 왜 만들었나
 *   숫자 하나(간격·깊이·쉼)를 바꾸려 해도 두 노트북의 폴더를 교체해야 했다. 대표 지시
 *   「서버 배포만으로도 편리하게 할 수 있게」 → 수집기는 이 파일의 **기본값**으로 돌고,
 *   서버가 5분마다(살아있음 신호 응답) · 매시(작업 목록 응답) 보내는 값으로 덮어쓴다.
 *
 * 🔴 넘지 않는 선(안전선 = FENCES)
 *   서버가 무슨 값을 보내도 이 범위를 못 넘는다. 범위 밖이면 **가장 가까운 선**으로 당긴다.
 *   형식이 틀리면(숫자 자리에 글자 등) 그 칸만 버리고 기본값을 쓴다.
 *   ⚠️ 안전선 자체는 서버가 못 바꾼다 — 서버 설정을 잘못 적어도 네이버를 몰아치지 못하게 하려는 장치다.
 *      바꾸려면 이 파일을 고치고 수집기를 교체한다(일부러 그렇게 둔다).
 *
 * ⚠️ 캡차 쉼(blockCooldownMs)은 서버가 **1시간 밑으로 줄일 수 없다**. 쉼을 원격으로 푸는 명령도 없다
 *    (대표 확정 ④ — 막힌 채 두드리면 차단이 깊어진다. 풀 때는 사람이 노트북에서).
 * ⚠️ 서버 설정을 못 받으면 마지막으로 받은 값, 그것도 없으면 DEFAULTS = 지금(v1.26.0)과 똑같이 돈다.
 *
 * chrome 의존 0 — background.js(importScripts)와 node 시험, 서버 파이썬 시험(node 로 이 파일을
 * 실행해 DEFAULTS·FENCES 를 서버 기본값과 대조)이 **같은 파일**을 읽는다. 한 규칙 한 곳.
 * ⚠️ 전부 IIFE 안에 둔다 — 전역에는 RemoteSettings 하나만(rank_rules.js 와 같은 이유).
 */
(function () {

  /* 기본값 = v1.26.0 코드에 박혀 있던 값 그대로. 바꾸면 서버 기본값(backend/collector_settings.py)도 같이. */
  const DEFAULTS = Object.freeze({
    // ── 속도 · 간격 ──
    spreadMinMs: 40000,        // 키워드 사이 최소 간격
    spreadLo: 0.4,             // 간격 흔들림 하한(평균 대비 배수)
    spreadHi: 1.8,             // 간격 흔들림 상한
    pageGapMinMs: 1200,        // 페이지 넘김 사이 간격(최소)
    pageGapMaxMs: 3000,        // 페이지 넘김 사이 간격(최대)
    hourBudgetMs: 3000000,     // 한 회차에 쓰는 시간(50분)
    hourTailMs: 300000,        // 시간대 끝 여유(5분)
    onDemandGapMs: 20000,      // 요청 건(온디맨드) 사이 간격
    onDemandHourCap: 12,       // 요청 건 시간당 상한
    portalHomeMinMs: 900,      // 네이버 첫 화면에서 머무는 시간
    portalHomeMaxMs: 1800,
    portalSearchMinMs: 2000,   // 통합검색 화면에서 머무는 시간
    portalSearchMaxMs: 3200,
    scrollPxMin: 500,          // 스크롤 한 번 폭
    scrollPxMax: 820,
    scrollWaitMinMs: 180,      // 스크롤 사이 쉼
    scrollWaitMaxMs: 440,
    // ── 깊이 · 판독 ──
    pagesPerKeyword: 8,        // 키워드당 넘기는 페이지(40개 × 8 ≈ 300위)
    readTries: 12,             // 1페이지 판독 재시도
    readTriesPaged: 36,        // 2페이지부터 내용이 바뀔 때까지 기다림(×0.8초 ≈ 29초)
    readGapMs: 800,            // 되읽기 간격
    // ── 차단 · 안전 ──
    blockCooldownMs: 21600000, // 캡차를 만나면 쉬는 시간(6시간)
    slowWindowMs: 86400000,    // 막힌 뒤 느리게 가는 기간(24시간)
    slowFactor: 2,             // 느리게 갈 때 간격 배수
    maxConsecutiveFail: 5,     // 연속 실패 몇 번이면 회차 중단
    // ── 보고 · 보관 ──
    heartbeatMin: 5,           // 살아있음 신호 주기(분)
    logKeep: 200,              // 팝업 로그 보관 줄 수
    outboxMaxItems: 100,       // 미전송 보관함 최대 건수
    outboxMaxAttempts: 6,      // 보관함 재시도 횟수
    dailyDueMs: 300000,        // 정시 회차 양보 신호 유효 시간
    // ── 판별 목록(더하기만) ──
    extraBlockPhrases: [],     // 차단 화면 문구 — 코드에 박힌 7개에 **더해진다**(뺄 수 없다)
    // ── 이 기계 · 스위치 ──
    machinePaused: false,      // 이 기계만 멈춤(서버) — 팝업 일시정지·화면 전체 끄기와 별개
    swEarlyStop: true,         // 찾을 상품을 다 찾으면 일찍 멈추기
    swUploadPartial: true,     // 부분 수집(막히기 전까지 담은 것) 올리기
    swTapProbe: true,          // 막힐 때 화면 응답 요약 보고(진단)
    swSearchEntry: null,       // 검색창으로 들어가기 — null = 팝업 설정을 따름
    swCoordinated: null,       // 서버 중앙 배정(v2) — null = 팝업 설정을 따름
  });

  /* 안전선 — [최소, 최대]. 서버가 못 바꾼다. */
  const MIN = 60 * 1000, HOUR = 60 * MIN;
  const FENCES = Object.freeze({
    spreadMinMs: [20000, 10 * MIN],
    spreadLo: [0.3, 3],
    spreadHi: [0.3, 3],
    pageGapMinMs: [800, 30000],
    pageGapMaxMs: [800, 30000],
    hourBudgetMs: [10 * MIN, 55 * MIN],
    hourTailMs: [2 * MIN, 20 * MIN],
    onDemandGapMs: [15000, 10 * MIN],
    onDemandHourCap: [0, 20],
    portalHomeMinMs: [500, 15000],
    portalHomeMaxMs: [500, 15000],
    portalSearchMinMs: [500, 15000],
    portalSearchMaxMs: [500, 15000],
    scrollPxMin: [200, 1500],
    scrollPxMax: [200, 1500],
    scrollWaitMinMs: [100, 3000],
    scrollWaitMaxMs: [100, 3000],
    pagesPerKeyword: [1, 10],
    readTries: [5, 40],
    readTriesPaged: [5, 60],
    readGapMs: [300, 3000],
    blockCooldownMs: [1 * HOUR, 48 * HOUR],
    slowWindowMs: [0, 72 * HOUR],
    slowFactor: [1, 5],
    maxConsecutiveFail: [1, 10],
    heartbeatMin: [1, 30],
    logKeep: [50, 1000],
    outboxMaxItems: [20, 300],
    outboxMaxAttempts: [1, 12],
    dailyDueMs: [1 * MIN, 30 * MIN],
  });
  /* 정수여야 하는 칸 — 소수가 오면 반올림한다. */
  const INTEGER_KEYS = Object.freeze([
    'onDemandHourCap', 'pagesPerKeyword', 'readTries', 'readTriesPaged', 'maxConsecutiveFail',
    'heartbeatMin', 'logKeep', 'outboxMaxItems', 'outboxMaxAttempts',
  ]);
  /* 최소·최대 짝 — 뒤집혀 오면 최대를 최소에 맞춘다(작은 쪽을 믿는다 = 느린 쪽이 아니라 좁은 쪽). */
  const PAIRS = Object.freeze([
    ['spreadLo', 'spreadHi'], ['pageGapMinMs', 'pageGapMaxMs'],
    ['portalHomeMinMs', 'portalHomeMaxMs'], ['portalSearchMinMs', 'portalSearchMaxMs'],
    ['scrollPxMin', 'scrollPxMax'], ['scrollWaitMinMs', 'scrollWaitMaxMs'],
  ]);
  const BOOL_KEYS = Object.freeze(['machinePaused', 'swEarlyStop', 'swUploadPartial', 'swTapProbe']);
  const NULLABLE_BOOL_KEYS = Object.freeze(['swSearchEntry', 'swCoordinated']);
  const PHRASE_MAX = 20, PHRASE_MIN_LEN = 2, PHRASE_MAX_LEN = 60;

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  /** 서버 값 → 적용할 값. 반환 { values, clamped:[키], rejected:[키] }.
   *  ⚠️ 절대 예외를 밖으로 내지 않는다 — 설정 문제로 수집이 죽으면 본말전도다. */
  function merge(server) {
    const values = {};
    Object.keys(DEFAULTS).forEach((k) => {
      const d = DEFAULTS[k];
      values[k] = Array.isArray(d) ? d.slice() : d;
    });
    const clamped = [], rejected = [];
    const src = (server && typeof server === 'object' && !Array.isArray(server)) ? server : {};
    Object.keys(src).forEach((k) => {
      try {
        if (!Object.prototype.hasOwnProperty.call(DEFAULTS, k)) { rejected.push(k); return; }
        const v = src[k];
        if (FENCES[k]) {
          const n = typeof v === 'number' ? v : NaN;
          if (!isFinite(n)) { rejected.push(k); return; }
          let x = INTEGER_KEYS.indexOf(k) >= 0 ? Math.round(n) : n;
          const c = clamp(x, FENCES[k][0], FENCES[k][1]);
          if (c !== x) clamped.push(k);
          values[k] = c;
        } else if (BOOL_KEYS.indexOf(k) >= 0) {
          if (typeof v !== 'boolean') { rejected.push(k); return; }
          values[k] = v;
        } else if (NULLABLE_BOOL_KEYS.indexOf(k) >= 0) {
          if (v !== null && typeof v !== 'boolean') { rejected.push(k); return; }
          values[k] = v;
        } else if (k === 'extraBlockPhrases') {
          if (!Array.isArray(v)) { rejected.push(k); return; }
          const out = [];
          v.forEach((s) => {
            if (typeof s !== 'string') return;
            const t = s.trim();
            if (t.length < PHRASE_MIN_LEN || t.length > PHRASE_MAX_LEN) return;
            if (out.indexOf(t) < 0 && out.length < PHRASE_MAX) out.push(t);
          });
          if (out.length !== v.length) clamped.push(k);
          values[k] = out;
        } else {
          rejected.push(k);
        }
      } catch (e) { rejected.push(k); }
    });
    PAIRS.forEach(([lo, hi]) => {
      if (values[lo] > values[hi]) { values[hi] = values[lo]; clamped.push(hi); }
    });
    return { values, clamped, rejected };
  }

  /** 차단 문구 검사용 — 코드에 박힌 문구에 서버 문구를 **더한** 목록. 빼는 길은 없다. */
  function blockPhrases(builtin, extra) {
    const out = (builtin || []).slice();
    (extra || []).forEach((s) => { if (typeof s === 'string' && s && out.indexOf(s) < 0) out.push(s); });
    return out;
  }

  /** 서버가 보낸 한 번짜리 명령 중 아직 안 한 것만 — 만료(until)된 것·모르는 명령·이미 한 것은 뺀다. */
  const COMMAND_KINDS = Object.freeze(['runNow', 'rearmAlarms', 'flushOutbox', 'uploadLogs', 'uploadDiag']);
  function pendingCommands(list, doneIds, nowMs) {
    const done = new Set(Array.isArray(doneIds) ? doneIds : []);
    const now = typeof nowMs === 'number' ? nowMs : Date.now();
    const out = [];
    (Array.isArray(list) ? list : []).forEach((c) => {
      if (!c || typeof c !== 'object') return;
      const id = typeof c.id === 'string' ? c.id.trim() : '';
      if (!id || id.length > 60 || done.has(id)) return;
      if (COMMAND_KINDS.indexOf(c.kind) < 0) return;
      const until = Date.parse(String(c.until || ''));
      if (!isFinite(until) || until < now) return;     // 만료 = 새로 설치한 기계가 옛 명령을 따라 하지 않게
      out.push({ id, kind: c.kind });
    });
    return out;
  }

  const RemoteSettings = { DEFAULTS, FENCES, INTEGER_KEYS, PAIRS, BOOL_KEYS, NULLABLE_BOOL_KEYS,
                           COMMAND_KINDS, merge, blockPhrases, pendingCommands };
  if (typeof module !== 'undefined' && module.exports) module.exports = RemoteSettings;
  if (typeof globalThis !== 'undefined') globalThis.RemoteSettings = RemoteSettings;
})();
