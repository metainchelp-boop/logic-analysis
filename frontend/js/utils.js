/* ===== 로직 분석 — API 헬퍼 & 유틸리티 ===== */

// ===== 앱 버전 (한 곳에서 관리) =====
var APP_VERSION = window.APP_VERSION = 'v5.3.3';

// ===== 401 중복 새로고침 방지 플래그 =====
var _isAuthRedirecting = false;

// ===== 토스트 알림 시스템 =====
var toast = (function() {
    var container = null;
    function _getContainer() {
        if (container) return container;
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
        document.body.appendChild(container);
        return container;
    }
    function show(message, type) {
        var colors = {
            error: { bg: '#FEE2E2', border: '#EF4444', text: '#991B1B', icon: '\u274C' },
            success: { bg: '#DCFCE7', border: '#22C55E', text: '#166534', icon: '\u2705' },
            warn: { bg: '#FEF9C3', border: '#EAB308', text: '#854D0E', icon: '\u26A0\uFE0F' },
            info: { bg: '#DBEAFE', border: '#3B82F6', text: '#1E40AF', icon: '\u2139\uFE0F' }
        };
        var c = colors[type] || colors.info;
        var el = document.createElement('div');
        el.style.cssText = 'background:' + c.bg + ';border:1px solid ' + c.border + ';color:' + c.text + ';padding:12px 18px;border-radius:10px;font-size:13px;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,0.12);pointer-events:auto;max-width:380px;opacity:0;transform:translateX(40px);transition:all 0.3s ease;';
        el.textContent = c.icon + '  ' + message;
        _getContainer().appendChild(el);
        requestAnimationFrame(function() { el.style.opacity = '1'; el.style.transform = 'translateX(0)'; });
        setTimeout(function() {
            el.style.opacity = '0'; el.style.transform = 'translateX(40px)';
            setTimeout(function() { if (el.parentNode) el.parentNode.removeChild(el); }, 300);
        }, type === 'error' ? 5000 : 3000);
    }
    return {
        error: function(msg) { show(msg, 'error'); },
        success: function(msg) { show(msg, 'success'); },
        warn: function(msg) { show(msg, 'warn'); },
        info: function(msg) { show(msg, 'info'); }
    };
})();

// API 헬퍼 (인증 토큰 자동 포함 + 에러 토스트)
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
function _handleResponse(r) {
    if (!r.ok) {
        var status = r.status;
        if (status === 401) {
            // 세션 만료로 리로드하는 조건:
            // 1) 로그인 API가 아닐 것 (로그인 실패 401은 정상)
            // 2) 현재 토큰이 있을 것 (비로그인 상태면 리로드 불필요)
            // 3) 아직 리다이렉트 중이 아닐 것 (중복 방지)
            var isLoginRequest = r.url && r.url.indexOf('/auth/login') !== -1;
            var hasToken = false;
            try { hasToken = !!sessionStorage.getItem('logic_token'); } catch(e) {}
            if (!isLoginRequest && hasToken && !_isAuthRedirecting) {
                _isAuthRedirecting = true;
                toast.error('인증이 만료되었습니다. 다시 로그인해주세요.');
                try { sessionStorage.removeItem('logic_token'); sessionStorage.removeItem('logic_user'); } catch(e) {}
                setTimeout(function() { location.reload(); }, 1500);
                return Promise.resolve({ success: false, detail: '인증 만료' });
            }
        } else if (status === 403) {
            toast.error('접근 권한이 없습니다.');
        } else if (status >= 500) {
            toast.error('서버 오류가 발생했습니다. (' + status + ')');
        }
        return r.json().catch(function() { return { success: false, detail: '요청 실패 (' + status + ')' }; })
            .then(function(body) {
                if (body && typeof body === 'object' && !body.hasOwnProperty('success')) {
                    body.success = false;
                }
                return body;
            });
    }
    return r.json().then(function(body) {
        if (body && typeof body === 'object' && !body.hasOwnProperty('success')) {
            body.success = true;
        }
        return body;
    });
}
function _handleNetworkError(e) {
    toast.error('네트워크 연결 오류 — 인터넷 연결을 확인해주세요.');
    throw e;
}
var api = {
    get: function(url) {
        return fetch(API_BASE + url, { headers: _authHeaders() }).then(_handleResponse).catch(_handleNetworkError);
    },
    post: function(url, body) {
        return fetch(API_BASE + url, {
            method: 'POST',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(body),
        }).then(_handleResponse).catch(_handleNetworkError);
    },
    put: function(url, body) {
        return fetch(API_BASE + url, {
            method: 'PUT',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(body),
        }).then(_handleResponse).catch(_handleNetworkError);
    },
    del: function(url) {
        return fetch(API_BASE + url, { method: 'DELETE', headers: _authHeaders() }).then(_handleResponse).catch(_handleNetworkError);
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

// ===== 공통 유틸리티 (리팩토링 v3.9.11) =====

// 순위 뱃지 (1~3위 금/은/동)
function getRankBadge(rank) {
    if (rank <= 3) {
        var cls = rank === 1 ? 'gold' : rank === 2 ? 'silver' : 'bronze';
        return React.createElement('span', { className: 'rank-badge ' + cls }, rank);
    }
    return rank;
}

// SEO 점수 색상
function scoreColor(s) {
    return s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626';
}

// SEO 점수 배경색
function scoreBg(s) {
    return s >= 70 ? '#ecfdf5' : s >= 40 ? '#fffbeb' : '#fef2f2';
}

// 순위별 CTR 테이블 (1~80위, 업계 벤치마크)
var CTR_TABLE = [
    0.080,0.070,0.060,0.050,0.030,0.025,0.020,0.018,0.016,0.015,
    0.013,0.012,0.011,0.010,0.010,0.009,0.009,0.008,0.008,0.008,
    0.007,0.007,0.006,0.006,0.006,0.005,0.005,0.005,0.005,0.005,
    0.004,0.004,0.004,0.004,0.004,0.003,0.003,0.003,0.003,0.003,
    0.0028,0.0026,0.0024,0.0022,0.0020,0.0019,0.0018,0.0017,0.0016,0.0015,
    0.0014,0.0013,0.0013,0.0012,0.0012,0.0011,0.0011,0.0010,0.0010,0.0010,
    0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,
    0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010,0.0010
];

// CTR 가져오기 (rank: 1-based)
function getCTR(rank) {
    return rank >= 1 && rank <= CTR_TABLE.length ? CTR_TABLE[rank - 1] : 0.001;
}
