/* ===== 로직 분석 — API 헬퍼 & 유틸리티 ===== */

// ===== 앱 버전 (한 곳에서 관리) =====
var APP_VERSION = window.APP_VERSION = 'v7.0.0';

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
                // ⚠️ FastAPI 422(요청 형식 오류)는 detail 이 **객체 배열**이라, 화면들이
                //    toast.error(res.detail) 하면 「[object Object]」만 뜬다(2026-08-05 신고).
                //    detail 을 여기서 한 번만 사람이 읽을 문장으로 바꿔 전 화면을 함께 고친다.
                if (body && typeof body === 'object' && body.detail && typeof body.detail !== 'string') {
                    body.detailRaw = body.detail;   // 원문 보존(진단용)
                    var d = body.detail;
                    try {
                        if (Array.isArray(d)) {
                            body.detail = d.map(function(x) {
                                var where = Array.isArray(x && x.loc) ? x.loc.filter(function(v) {
                                    return v !== 'body';
                                }).join('.') : '';
                                var msg = (x && (x.msg || x.message)) || '형식 오류';
                                return where ? (where + ': ' + msg) : msg;
                            }).join(' · ');
                        } else {
                            body.detail = (d && (d.msg || d.message)) || JSON.stringify(d);
                        }
                    } catch (e) { body.detail = '요청 형식 오류 (' + status + ')'; }
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
    patch: function(url, body) {
        return fetch(API_BASE + url, {
            method: 'PATCH',
            headers: _authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(body),
        }).then(_handleResponse).catch(_handleNetworkError);
    },
};

// 숫자 포맷팅
function fmt(n) {
    return n != null ? Number(n).toLocaleString() : '-';
}

// 리뷰 실측 앵커 — '자사 상품' 월판매·월매출 단일 계산(모든 섹션 공통).
//   판매량 추정 배너·시장 규모 보정이 같은 값을 쓰도록 여기서 한 번만 계산한다.
//   가정: 식품 평균 리뷰 작성률 11.6% · 운영 12개월. (rc/rate=누적판매, ÷12=월판매)
window.REVIEW_WRITE_RATE = 0.116;
window.reviewAnchorEstimate = function reviewAnchorEstimate(reviewCount, price) {
    var rc = Number(reviewCount) || 0;
    if (rc <= 0) return null;
    var rate = window.REVIEW_WRITE_RATE;
    var cumSales = Math.round(rc / rate);
    var monthlyUnits = Math.round(cumSales / 12);
    var p = Number(price) || 0;
    return {
        reviewCount: rc,
        cumSales: cumSales,
        monthlyUnits: monthlyUnits,
        monthlyRevenue: p > 0 ? monthlyUnits * p : null,
    };
};

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

// 붙여넣은 상품 페이지 HTML에서 상품 URL 자동 추출 (URL 따로 입력 불필요)
// 우선순위: og:url 메타 → canonical → HTML 내 네이버 쇼핑 상품 URL 패턴
// 지원 호스트: smartstore / brand(브랜드스토어) / shopping(가격비교) + m. 서브도메인
var _naverProductUrlRe = /https?:\/\/(?:[a-z0-9-]+\.)*(?:smartstore|brand|shopping)\.naver\.com(?:\/[A-Za-z0-9_-]+)?\/(?:products|catalog)\/\d+/g;
// og:url/canonical 검증용 — 가격비교(search.shopping.naver.com/catalog/123)처럼
// 도메인 바로 뒤에 catalog/products가 오는 경우까지 허용 (중간 경로 0개 이상)
var _naverProductUrlTest = /naver\.com\/(?:[\w-]+\/)*(?:products|catalog)\/\d+/;
function extractProductUrlFromHtml(html) {
    if (!html || typeof html !== 'string') return '';
    try {
        // JSON(window 상태 등) 안의 URL은 슬래시가 "\/" 로 이스케이프돼 있어
        // 정규식이 못 잡는다 → 사본에서 슬래시를 복원해 함께 검사한다.
        var h = html.indexOf('\\/') >= 0 ? html.replace(/\\\//g, '/') : html;
        var m;
        m = h.match(/<meta[^>]+property=["']og:url["'][^>]*content=["']([^"']+)["']/i)
            || h.match(/<meta[^>]+content=["']([^"']+)["'][^>]*property=["']og:url["']/i);
        if (m && m[1] && _naverProductUrlTest.test(m[1])) return m[1].split('?')[0];
        m = h.match(/<link[^>]+rel=["']canonical["'][^>]*href=["']([^"']+)["']/i)
            || h.match(/<link[^>]+href=["']([^"']+)["'][^>]*rel=["']canonical["']/i);
        if (m && m[1] && _naverProductUrlTest.test(m[1])) return m[1].split('?')[0];
        // 3) HTML 내 네이버 쇼핑 상품 URL 중 '가장 많이 등장하는 것' = 본 상품
        //    (추천/광고 상품은 보통 1번만 나옴 → 빈도로 본 상품 구별, 2회 이상만 신뢰)
        //    smartstore 외에 brand(브랜드스토어)·shopping(가격비교)·m. 모바일도 인식
        var all = h.match(_naverProductUrlRe);
        if (all && all.length) {
            var counts = {};
            for (var i = 0; i < all.length; i++) { var u = all[i].split('?')[0]; counts[u] = (counts[u] || 0) + 1; }
            var best = '', bestN = 0;
            for (var k in counts) { if (counts[k] > bestN) { bestN = counts[k]; best = k; } }
            if (best && bestN >= 2) return best;
            // 2회 미만이라도 후보 상품 URL이 '단 하나'뿐이면 그것이 본 상품
            // (추천/광고 상품이 섞이지 않은 경우 → 오인식 위험 없이 추출 성공률 향상)
            if (best && Object.keys(counts).length === 1) return best;
        }
        // 못 찾으면 빈값 — '가짜 채널(/main/)·아무 상품번호'로 엉뚱한 상품을 잡는 것보다 안전.
        return '';
    } catch (e) {
        return '';
    }
}

// 저장용 상세분석 경량화 — 리뷰 배열을 20개로 제한(목록 조회 비대화 방지)
function trimHtmlDetail(hd) {
    if (!hd || typeof hd !== 'object') return hd;
    try {
        var copy = Object.assign({}, hd);
        if (copy.reviewData && Array.isArray(copy.reviewData.reviews)) {
            copy.reviewData = Object.assign({}, copy.reviewData, { reviews: copy.reviewData.reviews.slice(0, 20) });
        }
        return copy;
    } catch (e) { return hd; }
}
