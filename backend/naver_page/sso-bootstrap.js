/* 전산 SSO 수신부. head 첫 스크립트로 실행: 비밀값은 URL/저장소에 남기지 않는다. */
(function() {
    'use strict';
    var params = new URLSearchParams(window.location.search);
    var started = params.has('sso_start') || params.has('code');
    var legacyPresent = params.has('sso');
    var legacyToken = !started && params.getAll('sso').length === 1 ? params.get('sso') : '';
    var requestId = params.get('sso_start') || '';
    var ambiguous = params.has('code') || (started && legacyPresent) || params.getAll('sso_start').length !== 1;
    var used = false, settled = false, timer, verifier = '';
    var parent = window.opener;
    var resolveCode, rejectCode;
    var promise = new Promise(function(resolve, reject) { resolveCode = resolve; rejectCode = reject; });
    // 번들/React 로드 전에 실패해도 처리되지 않은 거절을 만들지 않는다.
    promise.catch(function() {});
    var api = window.__metaincSso = {
        started: started,
        legacyPresent: legacyPresent,
        error: '',
        takeLegacyToken: function() { var value = legacyToken; legacyToken = ''; return value; },
        consume: function() {
            if (used) return Promise.reject(new Error('이미 사용한 로그인 요청입니다.'));
            used = true;
            return promise;
        }
    };
    function detach() {
        window.removeEventListener('message', receive);
        if (timer) clearTimeout(timer);
        try { window.opener = null; } catch (_) {}
        parent = null;
    }
    function fail(entryCode) {
        if (settled) return;
        settled = true;
        verifier = '';
        detach();
        api.error = '전산에서 다시 열어 로그인해 주세요.';
        var error = new Error(api.error);
        error.entryCode = entryCode;
        rejectCode(error);
    }
    // 다른 스크립트, 메시지, 네트워크 요청보다 먼저 주소를 정리한다.
    try {
        if (started || legacyPresent) {
            var clean = new URL(window.location.href);
            ['sso_start', 'code', 'sso'].forEach(function(key) { clean.searchParams.delete(key); });
            window.history.replaceState({}, document.title, clean.pathname + clean.search + clean.hash);
        }
    } catch (_) { fail('NV-E08'); return; }
    if (!started) return;
    var erpOrigin = '';
    var allowed = ['https://metainc.co.kr', 'http://metainc.co.kr', 'https://www.metainc.co.kr', 'http://www.metainc.co.kr'];
    try { erpOrigin = new URL(document.referrer).origin; } catch (_) {}
    // referrer는 보조 정보다. 비어 있으면 허용된 전산 출처에만 준비 메시지를 보내고
    // 실제 응답의 origin/source/requestId와 PKCE로 검증한다. 임의 출처·내장 창은 계속 거절한다.
    if (ambiguous || !/^[A-Za-z0-9_-]{43}$/.test(requestId)) { fail('NV-E01'); return; }
    if (!parent) { fail('NV-E04'); return; }
    if (window.top !== window) { fail('NV-E05'); return; }
    if (document.referrer && allowed.indexOf(erpOrigin) < 0) { fail('NV-E03'); return; }
    var targets = erpOrigin ? [erpOrigin] : allowed;
    function base64url(bytes) {
        return btoa(String.fromCharCode.apply(null, bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }
    function receive(event) {
        if (settled || !verifier || event.source !== parent || targets.indexOf(event.origin) < 0) return;
        var data = event.data;
        if (!data || data.type !== 'METAINC_SSO_CODE' || data.requestId !== requestId) return;
        if (typeof data.code !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(data.code)) { fail('NV-E01'); return; }
        settled = true;
        var result = { code: data.code, codeVerifier: verifier };
        verifier = '';
        detach();
        resolveCode(result);
    }
    window.addEventListener('message', receive);
    timer = setTimeout(function() { fail('NV-E06'); }, 60000);
    try {
        verifier = base64url(window.crypto.getRandomValues(new Uint8Array(32)));
        window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)).then(function(hash) {
            if (settled) return;
            try {
                targets.forEach(function(origin) {
                    parent.postMessage({ type: 'METAINC_SSO_READY', requestId: requestId,
                        codeChallenge: base64url(new Uint8Array(hash)) }, origin);
                });
            } catch (_) { fail('NV-E09'); }
        }).catch(function() { fail('NV-E07'); });
    } catch (_) { fail('NV-E07'); }
})();
