/* ===== 로직 분석 v2.1 — API 헬퍼 & 유틸리티 ===== */

// API 헬퍼 (인증 토큰 자동 포함)
var API_BASE = '/api';
function _authHeaders(extra) {
    var headers = {};
    try {
        var token = sessionStorage.getItem('logic_token');
        if (token) headers['Authorization'] = 'Bearer ' + token;
    } catch(e) {}
    if (extra) { for (var k in extra) headers[k] = extra[k]; }
    return headers;
}
var api = {
    get: function(url) {
        return fetch(API_BASE + url, { headers: _authHeaders() }).then(function(r) { return r.json(); });
    },
    post: function(url, body) {
        return fetch(API_BASE + url, {
            method: 'POST',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(body),
        }).then(function(r) { return r.json(); });
    },
    put: function(url, body) {
        return fetch(API_BASE + url, {
            method: 'PUT',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(body),
        }).then(function(r) { return r.json(); });
    },
    del: function(url) {
        return fetch(API_BASE + url, { method: 'DELETE', headers: _authHeaders() }).then(function(r) { return r.json(); });
    },
};

// 숫자 포맷팅
function fmt(n) {
    return n != null ? Number(n).toLocaleString() : '-';
}

// 경쟁강도 라벨
function compLabel(c) {
    var map = { '낮음': '낮음', 'LOW': '낮음', '보통': '보통', 'MEDIUM': '보통', '높음': '높음', 'HIGH': '높음', '': '-' };
    return map[c] || c || '-';
}

// 경쟁강도 배지 클래스
function compClass(c) {
    var low = ['낮음', 'LOW', ''];
    var mid = ['보통', 'MEDIUM'];
    if (low.indexOf(c) !== -1) return 'badge-green';
    if (mid.indexOf(c) !== -1) return 'badge-amber';
    return 'badge-red';
}
