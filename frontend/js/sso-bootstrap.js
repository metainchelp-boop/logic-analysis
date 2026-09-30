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
    function fail() {
        if (settled) return;
        settled = true;
        verifier = '';
        detach();
        api.error = '전산에서 다시 열어 로그인해 주세요.';
        rejectCode(new Error(api.error));
    }
    // 다른 스크립트, 메시지, 네트워크 요청보다 먼저 주소를 정리한다.
    try {
        if (started || legacyPresent) {
            var clean = new URL(window.location.href);
            ['sso_start', 'code', 'sso'].forEach(function(key) { clean.searchParams.delete(key); });
            window.history.replaceState({}, document.title, clean.pathname + clean.search + clean.hash);
        }
    } catch (_) { fail(); return; }
    if (!started) return;
    var erpOrigin = '';
    var allowed = ['https://metainc.co.kr', 'http://metainc.co.kr', 'https://www.metainc.co.kr', 'http://www.metainc.co.kr'];
    try { erpOrigin = new URL(document.referrer).origin; } catch (_) {}
    if (ambiguous || !/^[A-Za-z0-9_-]{43}$/.test(requestId) || !parent || window.top !== window || allowed.indexOf(erpOrigin) < 0) {
        fail(); return;
    }
    function base64url(bytes) {
        return btoa(String.fromCharCode.apply(null, bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }
    function receive(event) {
        if (settled || !verifier || event.source !== parent || event.origin !== erpOrigin) return;
        var data = event.data;
        if (!data || data.type !== 'METAINC_SSO_CODE' || data.requestId !== requestId) return;
        if (typeof data.code !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(data.code)) { fail(); return; }
        settled = true;
        var result = { code: data.code, codeVerifier: verifier };
        verifier = '';
        detach();
        resolveCode(result);
    }
    window.addEventListener('message', receive);
    timer = setTimeout(fail, 60000);
    try {
        verifier = base64url(window.crypto.getRandomValues(new Uint8Array(32)));
        window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)).then(function(hash) {
            if (settled) return;
            parent.postMessage({ type: 'METAINC_SSO_READY', requestId: requestId,
                codeChallenge: base64url(new Uint8Array(hash)) }, erpOrigin);
        }).catch(fail);
    } catch (_) { fail(); }
})();
